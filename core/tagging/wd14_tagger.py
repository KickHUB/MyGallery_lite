from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image

from core.booru.booru_dict import normalize_booru_tag
from core.utils.path_utils import resolve_dest_path
from settings import (
    WD14_AUTO_TAG_ON_REFRESH,
    WD14_MODEL_PATH,
    WD14_PROVIDER_LIST,
    WD14_PROVIDER_MODE,
    WD14_TAGS_CSV,
    WD14_THRESHOLD_ARTIST,
    WD14_THRESHOLD_CHARACTER,
    WD14_THRESHOLD_COPYRIGHT,
    WD14_THRESHOLD_GENERAL,
    WD14_THRESHOLD_META,
    WD14_THRESHOLD_RATING,
)

try:
    import onnxruntime as ort
except Exception:  # pragma: no cover - handled at runtime
    ort = None

logger = logging.getLogger(__name__)

AUTO_WD14_SOURCE = "auto:wd14"


@dataclass
class TagRow:
    name: str
    category: int


@dataclass
class WDThresholds:
    general: float = 0.35
    artist: float = 0.35
    copyright: float = 0.35
    character: float = 0.85
    meta: float = 0.35

    topk_general: int = 50
    topk_artist: int = 20
    topk_copyright: int = 20
    topk_character: int = 20
    topk_meta: int = 30


@dataclass
class WDTaggerState:
    model_path: Optional[Path] = None
    csv_path: Optional[Path] = None
    session: Optional["ort.InferenceSession"] = None
    tag_rows: Optional[List[TagRow]] = None
    general_index: int = 0
    input_size: int = 448
    input_layout: str = "nchw"


_STATE = WDTaggerState()

_GPU_PROVIDERS = ("TensorrtExecutionProvider", "CUDAExecutionProvider", "DmlExecutionProvider")


def _parse_float(value: object, default: float) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def _resolve_model_path() -> Optional[Path]:
    raw = (WD14_MODEL_PATH or "").strip()
    if not raw:
        return None
    path = Path(raw)
    return path if path.exists() else None


def _resolve_csv_path(model_path: Path) -> Optional[Path]:
    raw = (WD14_TAGS_CSV or "").strip()
    if raw:
        path = Path(raw)
        if path.exists():
            return path
    candidates = [
        model_path.with_suffix(".csv"),
        model_path.parent / "selected_tags.csv",
    ]
    for cand in candidates:
        if cand.exists():
            return cand
    return None


def _parse_provider_list(value: str) -> List[str]:
    if not value:
        return []
    parts = [chunk.strip() for chunk in value.split(",")]
    return [p for p in parts if p]


def _build_provider_order() -> List[str]:
    available = ort.get_available_providers()
    explicit = _parse_provider_list(WD14_PROVIDER_LIST)
    if explicit:
        return [p for p in explicit if p in available]

    mode = (WD14_PROVIDER_MODE or "gpu_first").strip().lower()
    cpu_only = ["CPUExecutionProvider"] if "CPUExecutionProvider" in available else []
    gpu_candidates = [p for p in _GPU_PROVIDERS if p in available]
    remaining = [p for p in available if p not in gpu_candidates and p not in cpu_only]

    if mode in {"cpu", "cpu_only", "force_cpu"}:
        return cpu_only or available
    if mode in {"gpu_only", "force_gpu"}:
        return gpu_candidates or available
    if mode in {"cpu_first"}:
        return cpu_only + gpu_candidates + remaining
    return gpu_candidates + cpu_only + remaining


def _load_selected_tags(csv_path: Path) -> Tuple[List[TagRow], int]:
    rows: List[TagRow] = []
    general_index = -1
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader, None)
        if header is None:
            raise RuntimeError(f"Empty CSV: {csv_path}")
        for row in reader:
            if len(row) < 3:
                continue
            name = row[1].strip()
            try:
                cat = int(row[2])
            except Exception:
                cat = -1
            if general_index < 0 and cat == 0:
                general_index = len(rows)
            rows.append(TagRow(name=name, category=cat))
    if general_index < 0:
        general_index = 0
    return rows, general_index


def _preprocess_image(pil: Image.Image, size: int, layout: str) -> np.ndarray:
    pil = pil.convert("RGB")
    ratio = float(size) / max(pil.size)
    new_size = (int(pil.size[0] * ratio), int(pil.size[1] * ratio))
    pil_resized = pil.resize(new_size, Image.LANCZOS)

    square = Image.new("RGB", (size, size), (255, 255, 255))
    square.paste(
        pil_resized,
        ((size - new_size[0]) // 2, (size - new_size[1]) // 2),
    )

    arr = np.array(square).astype(np.float32)
    arr = arr[:, :, ::-1]  # RGB -> BGR
    if layout == "nchw":
        arr = np.transpose(arr, (2, 0, 1))
    arr = np.expand_dims(arr, 0)
    return arr


def _pick_rating(result: Sequence[Tuple[str, float]], general_index: int) -> Tuple[str, float]:
    candidates = [(t, p) for (t, p) in result if str(t).startswith("rating:")]
    if candidates:
        return max(candidates, key=lambda x: x[1])

    if general_index > 0:
        t, p = max(result[:general_index], key=lambda x: x[1])
        t = str(t).strip().lower()
        if t in ("general", "sensitive", "questionable", "explicit"):
            return (f"rating:{t}", float(p))
        return (str(t), float(p))

    return ("", 0.0)


def rating_to_code(rating_tag: str) -> Optional[int]:
    rt = (rating_tag or "").lower().strip()
    if rt.endswith("general"):
        return 0
    if rt.endswith("sensitive"):
        return 1
    if rt.endswith("questionable"):
        return 2
    if rt.endswith("explicit"):
        return 3
    return None


def _apply_thresholds(
    tag_rows: List[TagRow],
    probs: np.ndarray,
    thresholds: WDThresholds,
    general_index: int,
) -> Tuple[List[Tuple[str, float]], str, float]:
    result = [(tr.name, float(probs[i])) for i, tr in enumerate(tag_rows)]
    rating_tag, rating_prob = _pick_rating(result, general_index)

    buckets = {
        "general": [],
        "artist": [],
        "copyright": [],
        "character": [],
        "meta": [],
    }

    category_map = {
        0: "general",
        1: "artist",
        3: "copyright",
        4: "character",
        5: "meta",
    }

    for row, prob in zip(tag_rows, probs):
        name = row.name
        cat = category_map.get(row.category)
        if not cat:
            continue
        buckets[cat].append((name, float(prob)))

    def filter_bucket(name: str, threshold: float, topk: int) -> List[Tuple[str, float]]:
        items = [item for item in buckets.get(name, []) if item[1] >= threshold]
        items.sort(key=lambda x: x[1], reverse=True)
        return items[:topk]

    selected = []
    selected.extend(filter_bucket("general", thresholds.general, thresholds.topk_general))
    selected.extend(filter_bucket("artist", thresholds.artist, thresholds.topk_artist))
    selected.extend(filter_bucket("copyright", thresholds.copyright, thresholds.topk_copyright))
    selected.extend(filter_bucket("character", thresholds.character, thresholds.topk_character))
    selected.extend(filter_bucket("meta", thresholds.meta, thresholds.topk_meta))

    return selected, rating_tag, rating_prob


def _infer_input_spec(session: "ort.InferenceSession") -> tuple[int, str]:
    try:
        shape = session.get_inputs()[0].shape
    except Exception:
        return 448, "nchw"
    if len(shape) == 4:
        if shape[1] == 3:
            size = shape[2] if isinstance(shape[2], int) and shape[2] else 448
            return int(size), "nchw"
        if shape[3] == 3:
            size = shape[1] if isinstance(shape[1], int) and shape[1] else 448
            return int(size), "nhwc"
    for dim in reversed(shape):
        if isinstance(dim, int) and dim > 0:
            return int(dim), "nchw"
    return 448, "nchw"


def _ensure_session() -> WDTaggerState:
    global _STATE
    model_path = _resolve_model_path()
    if not model_path:
        raise RuntimeError("WD14 모델 경로가 설정되지 않았습니다.")
    if ort is None:
        raise RuntimeError("onnxruntime이 설치되어 있지 않습니다.")

    csv_path = _resolve_csv_path(model_path)
    if not csv_path:
        raise RuntimeError("WD14 태그 CSV 파일을 찾을 수 없습니다.")

    if _STATE.session and _STATE.model_path == model_path and _STATE.csv_path == csv_path:
        return _STATE

    provider_order = _build_provider_order()
    if not provider_order:
        provider_order = ["CPUExecutionProvider"]
    try:
        session = ort.InferenceSession(model_path.as_posix(), providers=provider_order)
    except Exception as exc:
        logger.warning("WD14 세션 초기화 실패, CPU로 폴백합니다: %s", exc)
        session = ort.InferenceSession(model_path.as_posix(), providers=["CPUExecutionProvider"])
    tag_rows, general_index = _load_selected_tags(csv_path)
    input_size, input_layout = _infer_input_spec(session)

    _STATE = WDTaggerState(
        model_path=model_path,
        csv_path=csv_path,
        session=session,
        tag_rows=tag_rows,
        general_index=general_index,
        input_size=input_size,
        input_layout=input_layout,
    )
    return _STATE


def reset_wd14_session() -> None:
    global _STATE
    _STATE = WDTaggerState()


def is_video_pair_image(path: Path) -> bool:
    name = path.name.lower()
    if name.startswith("video"):
        return True
    if "(video)" in name:
        return True
    if path.parent.name.lower() == "videos":
        return True
    return False


def _build_thresholds() -> WDThresholds:
    return WDThresholds(
        general=_parse_float(WD14_THRESHOLD_GENERAL, 0.35),
        artist=_parse_float(WD14_THRESHOLD_ARTIST, 0.35),
        copyright=_parse_float(WD14_THRESHOLD_COPYRIGHT, 0.35),
        character=_parse_float(WD14_THRESHOLD_CHARACTER, 0.85),
        meta=_parse_float(WD14_THRESHOLD_META, 0.35),
    )


def tag_image(abs_path: str) -> Tuple[List[str], Optional[int]]:
    state = _ensure_session()
    if not state.session or not state.tag_rows:
        raise RuntimeError("WD14 태거 세션이 준비되지 않았습니다.")

    with Image.open(abs_path) as image:
        arr = _preprocess_image(image, state.input_size, state.input_layout)

    input_name = state.session.get_inputs()[0].name
    outputs = state.session.run(None, {input_name: arr})
    if not outputs:
        raise RuntimeError("WD14 모델 출력이 비어 있습니다.")

    probs = outputs[0][0]
    thresholds = _build_thresholds()
    selected, rating_tag, rating_prob = _apply_thresholds(
        state.tag_rows,
        probs,
        thresholds,
        state.general_index,
    )

    rating_code = None
    rating_threshold = _parse_float(WD14_THRESHOLD_RATING, 0.0)
    if rating_tag and rating_prob >= rating_threshold:
        rating_code = rating_to_code(rating_tag)

    tags = []
    seen: set[str] = set()
    for raw_tag, _prob in selected:
        tag = normalize_booru_tag(raw_tag)
        if not tag or tag in seen:
            continue
        if tag.startswith("rating:"):
            continue
        seen.add(tag)
        tags.append(tag)

    return tags, rating_code


def auto_tag_rel_path(rel_path: str) -> Tuple[List[str], Optional[int]]:
    abs_path = resolve_dest_path(rel_path)
    if not abs_path:
        raise RuntimeError("이미지 경로가 올바르지 않습니다.")
    path = Path(abs_path)
    if is_video_pair_image(path):
        raise RuntimeError("영상 페어링 이미지는 자동 태깅에서 제외됩니다.")
    return tag_image(abs_path)


def should_auto_tag_on_refresh() -> bool:
    return bool(WD14_AUTO_TAG_ON_REFRESH)


__all__ = [
    "AUTO_WD14_SOURCE",
    "auto_tag_rel_path",
    "is_video_pair_image",
    "rating_to_code",
    "reset_wd14_session",
    "should_auto_tag_on_refresh",
    "tag_image",
]
