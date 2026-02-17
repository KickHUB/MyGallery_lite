from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Optional, Union

from .png_meta_menu import parse_png as _parse_png


def _normalize_png_metadata(result: Dict[str, Any]) -> Dict[str, Any]:
    expected_keys = [
        "seed",
        "steps",
        "cfg",
        "sampler",
        "scheduler",
        "denoise",
        "model_checkpoint",
        "models",
        "vae_name",
        "loras",
        "width",
        "height",
        "created",
        "workflow_id",
        "node_count",
        "guidance",
    ]
    for key in expected_keys:
        if key == "models":
            result.setdefault(key, [])
        else:
            result.setdefault(key, None)
    return result


_A1111_STEPS_RE = re.compile(r"(?i)\bsteps:\s*\d+")
_A1111_KEY_RE = re.compile(r"(?:^|,\s*|\n)\s*([A-Za-z][A-Za-z0-9 _/-]*?)\s*:\s*")


def _parse_a1111_kv(text: str) -> Dict[str, str]:
    if not text:
        return {}
    s = text.strip()
    if not s:
        return {}
    matches = list(_A1111_KEY_RE.finditer(s))
    if not matches:
        return {}
    kv: Dict[str, str] = {}
    for idx, match in enumerate(matches):
        key = (match.group(1) or "").strip()
        if not key:
            continue
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(s)
        value = s[start:end].strip()
        value = value.lstrip(", \n").rstrip(", ")
        kv[key] = value
    return kv


def _parse_a1111_parameters(raw: str) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    steps_match = _A1111_STEPS_RE.search(text)
    if not steps_match:
        return None

    lower = text.lower()
    neg_label = "negative prompt:"
    neg_pos = lower.find(neg_label)
    steps_pos = steps_match.start()

    positive = ""
    negative = ""
    params_text = text[steps_pos:]

    if neg_pos != -1 and neg_pos < steps_pos:
        positive = text[:neg_pos].strip()
        steps_match2 = _A1111_STEPS_RE.search(text[neg_pos:])
        if steps_match2:
            steps_pos2 = neg_pos + steps_match2.start()
            negative = text[neg_pos + len(neg_label):steps_pos2].strip()
            params_text = text[steps_pos2:]
        else:
            negative = text[neg_pos + len(neg_label):].strip()
            params_text = text[steps_pos:]
    else:
        positive = text[:steps_pos].strip()

    kv = _parse_a1111_kv(params_text)

    def _to_int(value: Optional[str]) -> Optional[int]:
        if value is None:
            return None
        try:
            return int(str(value).strip())
        except Exception:
            return None

    def _to_float(value: Optional[str]) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(str(value).strip())
        except Exception:
            return None

    steps = None
    sampler = None
    cfg = None
    seed = None
    width = None
    height = None
    model_checkpoint = None
    vae_name = None
    denoise = None

    for key, value in kv.items():
        key_low = key.lower()
        if key_low == "steps":
            steps = _to_int(value)
        elif key_low == "sampler":
            sampler = value
        elif key_low in {"cfg scale", "cfg"}:
            cfg = _to_float(value)
        elif key_low == "seed":
            seed = _to_int(value)
        elif key_low == "size":
            m = re.search(r"(\d+)\s*[xX]\s*(\d+)", value or "")
            if m:
                width = _to_int(m.group(1))
                height = _to_int(m.group(2))
        elif key_low == "model":
            model_checkpoint = value
        elif key_low == "vae":
            vae_name = value
        elif key_low == "denoising strength":
            denoise = _to_float(value)

    result: Dict[str, Any] = {
        "positive_prompt": positive,
        "negative_prompt": negative,
        "seed": seed,
        "steps": steps,
        "cfg": cfg,
        "sampler": sampler,
        "scheduler": None,
        "denoise": denoise,
        "width": width,
        "height": height,
        "model_checkpoint": model_checkpoint,
        "models": [model_checkpoint] if model_checkpoint else [],
        "vae_name": vae_name,
        "a1111_params": kv or None,
    }
    return result


def parse_png_metadata_with_status(
    path: Union[str, Path],
) -> tuple[Optional[Dict[str, Any]], str]:
    """ComfyUI PNG 메타데이터를 파싱하고 상태를 함께 반환한다."""
    png_path = Path(path)
    result, status = _parse_png(png_path)
    if status == "ok" and isinstance(result, dict):
        return _normalize_png_metadata(result), status

    if isinstance(result, dict):
        raw_params = result.get("parameters_raw")
        parsed = _parse_a1111_parameters(raw_params) if raw_params else None
        if parsed:
            if result.get("Prompt_raw"):
                parsed["Prompt_raw"] = result.get("Prompt_raw")
            if result.get("Workflow_raw"):
                parsed["Workflow_raw"] = result.get("Workflow_raw")
            if raw_params:
                parsed["parameters_raw"] = raw_params
            return _normalize_png_metadata(parsed), "ok"

    return None, status


def parse_png_metadata(path: Union[str, Path]) -> Optional[Dict[str, Any]]:
    """ComfyUI PNG 메타데이터를 파싱한다.

    :param path: PNG 파일 경로
    :return: 메타데이터 딕셔너리 또는 None
    """
    result, status = parse_png_metadata_with_status(path)
    if status != "ok":
        return None
    return result
