# core/tag_utils.py
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional, Union

from settings import DEST_FOLDER_NAME, DRAFTS_FOLDER_NAME
from core.media.gallery_layout import extract_date_from_path
from core.media.png_metadata import parse_png_metadata, parse_png_metadata_with_status
from core.media.video_meta import read_video_comfy_meta
import settings as _settings

PROMPT_KEYS: tuple[str, ...] = (
    "Prompt",
    "parameters",
    "Parameters",
    "Comment",
    "Description",
    "UserComment",
    "PNG:Prompt",
    "PNG:parameters",
    "PNG:Parameters",
)

_TAG_WHITELIST_RE = re.compile(r"^[\w\s\-+().:/#&'%]+$", re.UNICODE)

VIDEO_EXTS: tuple[str, ...] = (
    '.mp4', '.webm', '.mov', '.avi', '.mkv', '.gif',
)


def _is_video_file(path: str | os.PathLike) -> bool:
    try:
        return Path(path).suffix.lower() in VIDEO_EXTS
    except Exception:
        return False


def _looks_like_path_or_file(s: str) -> bool:
    if not s:
        return False
    t = s.strip()
    if not t:
        return False
    if len(t) < 6:
        return True
    if ':' in t and ('\\' in t or '/' in t):
        return True
    if re.search(r'\.(png|jpg|jpeg|webp|gif|mp4|webm|mov|avi|mkv)\b', t, re.I):
        return True
    return False


def _extract_comfy_positive_negative(prompt_graph: dict) -> tuple[str, str]:
    """Best-effort prompt text extraction from a ComfyUI graph dict."""

    if not isinstance(prompt_graph, dict):
        return '', ''

    nodes_obj = prompt_graph.get('nodes') if isinstance(prompt_graph.get('nodes'), dict) else prompt_graph
    if not isinstance(nodes_obj, dict):
        return '', ''

    pos_best = ('', -1)
    neg_best = ('', -1)
    any_best = ('', -1)

    def add_candidate(text: str, score: int, is_neg: bool | None = None):
        nonlocal pos_best, neg_best, any_best
        t = (text or '').strip()
        if not t:
            return
        if _looks_like_path_or_file(t):
            return
        if len(t) < 8:
            return
        if score > any_best[1]:
            any_best = (t, score)
        if is_neg is True:
            if score > neg_best[1]:
                neg_best = (t, score)
            return
        if is_neg is False:
            if score > pos_best[1]:
                pos_best = (t, score)
            return
        # unknown -> treat as positive candidate
        if score > pos_best[1]:
            pos_best = (t, score)

    for _nid, node in nodes_obj.items():
        if not isinstance(node, dict):
            continue
        inputs = node.get('inputs')
        if not isinstance(inputs, dict):
            continue
        class_type = str(node.get('class_type') or '').strip()
        class_low = class_type.lower()
        meta = node.get('_meta')
        title = ''
        if isinstance(meta, dict):
            title = str(meta.get('title') or meta.get('name') or '')
        title_low = title.lower()

        base_weight = 0
        if class_low in {'cliptextencode', 'cliptextencodesdxl'}:
            base_weight += 500
        if class_low in {'primitivestringmultiline', 'primitivestring'}:
            base_weight += 200
        if 'positive' in title_low:
            base_weight += 100
        if 'negative' in title_low:
            base_weight += 100

        is_neg_hint: bool | None = None
        if 'negative' in title_low or title_low.startswith('neg') or 'neg' in title_low:
            is_neg_hint = True
        elif 'positive' in title_low or title_low.startswith('pos'):
            is_neg_hint = False

        # Typical keys
        for key in ('text', 'value', 'prompt'):
            val = inputs.get(key)
            if isinstance(val, str):
                score = len(val.strip()) + base_weight
                add_candidate(val, score, is_neg_hint)

        # Fallback: scan all string inputs, but with lower weight
        for k, val in inputs.items():
            if isinstance(val, str) and k not in {'text', 'value', 'prompt'}:
                score = len(val.strip()) + base_weight - 100
                add_candidate(val, score, is_neg_hint)

    positive = pos_best[0] or any_best[0] or ''
    negative = neg_best[0] or ''
    return positive, negative

def _is_whitelisted_tag(tag: str) -> bool:
    if not tag:
        return False
    if any(token in tag for token in ('{', '}', '[', ']', '"')):
        return False
    if ": " in tag or " :" in tag:
        return False
    if not _TAG_WHITELIST_RE.match(tag):
        return False
    return any(ch.isalnum() for ch in tag)

def _looks_like_json_fragment_tag(tag: str) -> bool:
    if not tag:
        return False
    if any(token in tag for token in ('{', '}', '[', ']', '"')):
        return True
    if ": " in tag or " :" in tag:
        return True
    if re.search(r'"\s*:|:\s*"', tag):
        return True
    return False

def _filter_tags(tags: List[str]) -> List[str]:
    filtered: List[str] = []
    for tag in tags:
        normalized = tag.strip()
        if not normalized:
            continue
        if is_abnormal_tag(normalized):
            continue
        filtered.append(normalized)
    return filtered

def filter_tags(tags: List[str]) -> List[str]:
    return _filter_tags(tags)

def is_abnormal_tag(tag: str) -> bool:
    normalized = tag.strip()
    if not normalized:
        return False
    return _looks_like_json_fragment_tag(normalized) and not _is_whitelisted_tag(normalized)


def _resolve_exiftool_executable() -> str:
    configured = (getattr(_settings, "EXIFTOOL_PATH", "") or "").strip()
    if configured:
        try:
            if Path(configured).is_file():
                return configured
        except Exception:
            pass
    return "exiftool"


def _run_exiftool(path: Union[str, os.PathLike], fast: bool = True) -> Dict:
    exiftool_exe = _resolve_exiftool_executable()
    cmd = [
        exiftool_exe,
        "-j",
        "-a",
        "-G1",
        "-charset", "filename=UTF8",
    ]
    if fast:
        cmd += ["-fast", "-fast2"]
    cmd.append(str(path))
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    except FileNotFoundError:
        logging.warning("ExifTool is not installed or not found. Please install it to extract metadata.")
        return {}
    except Exception as exc:
        logging.warning("Failed to run ExifTool on %s: %s", path, exc)
        return {}

    if r.returncode != 0:
        logging.warning(
            "ExifTool exited with code %s for %s: %s", r.returncode, path, r.stderr.strip()
        )
        return {}

    try:
        data = json.loads(r.stdout or "[]")
        if isinstance(data, list) and data:
            return data[0]
    except Exception as exc:
        logging.warning("Failed to parse ExifTool output for %s: %s", path, exc)
    return {}


def _run_exiftool_with_reason(
    path: Union[str, os.PathLike],
    fast: bool = True,
) -> tuple[Dict, Optional[str]]:
    exiftool_exe = _resolve_exiftool_executable()
    cmd = [
        exiftool_exe,
        "-j",
        "-a",
        "-G1",
        "-charset", "filename=UTF8",
    ]
    if fast:
        cmd += ["-fast", "-fast2"]
    cmd.append(str(path))
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    except FileNotFoundError:
        logging.warning("ExifTool is not installed or not found. Please install it to extract metadata.")
        return {}, "exiftool_missing"
    except Exception as exc:
        logging.warning("Failed to run ExifTool on %s: %s", path, exc)
        return {}, "exiftool_failed"

    if r.returncode != 0:
        logging.warning(
            "ExifTool exited with code %s for %s: %s", r.returncode, path, r.stderr.strip()
        )
        return {}, "exiftool_error"

    try:
        data = json.loads(r.stdout or "[]")
        if isinstance(data, list) and data:
            return data[0], None
    except Exception as exc:
        logging.warning("Failed to parse ExifTool output for %s: %s", path, exc)
        return {}, "exiftool_parse_failed"
    return {}, "exiftool_no_data"

def get_meta_with_retry(path: Union[str, os.PathLike], tries: int = 5, delay: float = 0.8, use_fast: bool = True) -> Dict:
    path = str(path)
    meta: Dict = {}
    for _ in range(max(1, tries - 1)):
        meta = _run_exiftool(path, fast=use_fast)
        if _has_any_prompt(meta):
            return meta
        time.sleep(max(0.1, delay))
    meta = _run_exiftool(path, fast=False)
    return meta


def get_meta_with_retry_with_reason(
    path: Union[str, os.PathLike],
    tries: int = 5,
    delay: float = 0.8,
    use_fast: bool = True,
) -> tuple[Dict, Optional[str]]:
    path = str(path)
    meta: Dict = {}
    last_reason: Optional[str] = None
    for _ in range(max(1, tries - 1)):
        meta, reason = _run_exiftool_with_reason(path, fast=use_fast)
        if _has_any_prompt(meta):
            return meta, None
        last_reason = reason or last_reason
        if reason == "exiftool_missing":
            return {}, reason
        time.sleep(max(0.1, delay))
    meta, reason = _run_exiftool_with_reason(path, fast=False)
    if _has_any_prompt(meta):
        return meta, None
    if meta:
        return meta, "exiftool_no_prompt"
    return meta, reason or last_reason or "exiftool_no_prompt"

def _has_any_prompt(meta: Dict) -> bool:
    for k in PROMPT_KEYS:
        v = meta.get(k)
        if isinstance(v, str) and v.strip():
            return True
    return False

def _looks_like_comfy_json(s: str) -> bool:
    s = s.strip()
    return s.startswith("{") and s.endswith("}") and '"class_type"' in s

def _looks_like_json_fragment_text(text: str) -> bool:
    if not text:
        return False
    stripped = text.strip()
    if stripped.startswith(("{", "[")) or stripped.endswith(("}", "]")):
        if ":" in stripped or '"' in stripped:
            return True
    if '"' in stripped and ":" in stripped:
        return True
    return False

def extract_tags_from_meta(meta: Dict) -> Optional[Dict]:
    raw: Optional[str] = None
    for k in PROMPT_KEYS:
        v = meta.get(k)
        if isinstance(v, str) and v.strip():
            raw = v.strip()
            break
    if not raw:
        return None
    if _looks_like_json_fragment_text(raw) and not _looks_like_comfy_json(raw):
        return None

    positive: Optional[str] = None
    negative: Optional[str] = None
    model: Optional[str] = None

    if _looks_like_comfy_json(raw):
        try:
            nodes = json.loads(raw)
            if isinstance(nodes, dict):
                for node in nodes.values():
                    if not isinstance(node, dict):
                        continue
                    ct = node.get("class_type")
                    if ct == "CLIPTextEncode":
                        title = (node.get("_meta", {}) or {}).get("title", "").lower()
                        text = (node.get("inputs", {}) or {}).get("text")
                        if isinstance(text, str):
                            if "positive" in title:
                                positive = text
                            elif "negative" in title:
                                negative = text
                    elif ct == "CheckpointLoaderSimple":
                        model = (node.get("inputs", {}) or {}).get("ckpt_name") or model
        except Exception:
            pass

    if positive is None and negative is None:
        low = raw.lower()
        idx = low.find("negative prompt:")
        if idx != -1:
            positive = raw[:idx].strip(" \n,")
            negative = raw[idx + len("negative prompt:"):].strip()
        else:
            positive = raw

    return {
        "raw_prompt": raw,
        "positive": positive,
        "negative": negative,
        "model": _basename_only(model),
    }


def _basename_only(value: Optional[str]) -> Optional[str]:
    if not value:
        return value
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("\\", "/")
    return text.rsplit("/", 1)[-1]

def _to_rel_file_key(path: Union[str, os.PathLike]) -> str:
    p = str(path)
    if DEST_FOLDER_NAME in p:
        tail = p.split(DEST_FOLDER_NAME, 1)[-1].lstrip("/\\")
        rel = os.path.join(DEST_FOLDER_NAME, tail)
    else:
        rel = p
    if rel and rel.replace("\\", "/").lower().startswith(f"{DRAFTS_FOLDER_NAME.lower()}/") and DEST_FOLDER_NAME:
        rel = os.path.join(DEST_FOLDER_NAME, rel)
    return rel.replace("\\", "/")

def _date_from_rel(rel: str, default: str = "unknown") -> str:
    """Extract YYYY-MM-DD from DB relative path (supports legacy/new layouts)."""
    return extract_date_from_path(rel, default=default)

def _split_tags(s: Optional[str]) -> List[str]:
    if not s:
        return []
    raw_tags = [t.strip().replace("_", " ") for t in s.replace("\n", " ").split(",") if t.strip()]
    return _filter_tags(raw_tags)

def _build_prompt_result_from_png_data(
    data: Dict,
    rel: str,
    date: Optional[str],
) -> Dict:
    positive = data.get("positive_prompt") or ""
    negative = data.get("negative_prompt") or ""
    known = {
        "positive_prompt",
        "negative_prompt",
        "model_checkpoint",
        "models",
        "vae_name",
        "loras",
        "seed",
        "steps",
        "cfg",
        "sampler",
        "scheduler",
        "denoise",
        "width",
        "height",
        "created",
        "workflow_id",
        "node_count",
        "guidance",
    }
    extras = {k: v for k, v in data.items() if k not in known}
    if not extras:
        extras = None
    raw_models = data.get("models")
    models: List[str] = []
    if isinstance(raw_models, (list, tuple)):
        models = [_basename_only(str(m).strip()) for m in raw_models if str(m).strip()]
        models = [m for m in models if m]
    elif isinstance(raw_models, str) and raw_models.strip():
        model_value = _basename_only(raw_models.strip())
        models = [model_value] if model_value else []
    if not models and data.get("model_checkpoint"):
        model_value = _basename_only(str(data.get("model_checkpoint")).strip())
        if model_value:
            models = [model_value]
    model_name = models[0] if models else (data.get("model_checkpoint") or "")
    model_name = _basename_only(model_name) or ""
    loras = data.get("loras")
    if isinstance(loras, list):
        normalized_loras = []
        for entry in loras:
            if not isinstance(entry, dict):
                continue
            name = _basename_only(entry.get("name"))
            if not name:
                continue
            normalized_loras.append({**entry, "name": name})
        loras = normalized_loras or None
    return {
        "file": rel,
        "date": date,
        "model": model_name,
        "models": models,
        "positive": positive,
        "negative": negative,
        "tags_positive": _split_tags(positive),
        "tags_negative": _split_tags(negative),
        "seed": data.get("seed"),
        "steps": data.get("steps"),
        "cfg": data.get("cfg"),
        "sampler": data.get("sampler"),
        "scheduler": data.get("scheduler"),
        "denoise": data.get("denoise"),
        "model_checkpoint": _basename_only(data.get("model_checkpoint")),
        "vae_name": data.get("vae_name"),
        "loras": loras,
        "width": data.get("width"),
        "height": data.get("height"),
        "created": data.get("created"),
        "workflow_id": data.get("workflow_id"),
        "node_count": data.get("node_count"),
        "guidance": data.get("guidance"),
        "extras": extras,
    }


def _build_prompt_result_from_meta(
    info: Dict,
    meta: Optional[Dict],
    rel: str,
    date: Optional[str],
) -> Dict:
    positive = info.get("positive") or ""
    negative = info.get("negative") or ""
    lora_matches = re.findall(r"<lora:([^:>]+):([^>]+)>", f"{positive} {negative}")
    loras = None
    if lora_matches:
        parsed_loras = []
        for name, strength in lora_matches:
            name = _basename_only(name.strip())
            strength_value: Union[str, float] = strength.strip()
            try:
                strength_value = float(strength_value)
            except ValueError:
                pass
            if name:
                parsed_loras.append({"name": name, "strength": strength_value})
        if parsed_loras:
            loras = parsed_loras
    model_name = _basename_only(info.get("model")) or ""
    models = [model_name] if model_name else []
    return {
        "file": rel,
        "date": date,
        "model": model_name,
        "models": models,
        "positive": positive,
        "negative": negative,
        "tags_positive": _split_tags(positive),
        "tags_negative": _split_tags(negative),
        "seed": None,
        "steps": None,
        "cfg": None,
        "sampler": None,
        "scheduler": None,
        "denoise": None,
        "model_checkpoint": model_name or None,
        "vae_name": None,
        "loras": loras,
        "width": None,
        "height": None,
        "created": None,
        "workflow_id": None,
        "node_count": None,
        "guidance": None,
        "extras": None,
    }


def extract_prompt_with_reason(
    file_path: Union[str, os.PathLike],
) -> tuple[Optional[Dict], Optional[str]]:
    # Video: read from ffprobe tags (comment/description) first.
    if _is_video_file(file_path):
        rel = _to_rel_file_key(file_path)
        date = _date_from_rel(rel)
        try:
            meta = read_video_comfy_meta(Path(file_path), _settings)
            prompt_raw = meta.get("prompt")
            workflow = meta.get("workflow")
            comment_raw = meta.get("comment_raw")

            positive = ""
            negative = ""
            if isinstance(prompt_raw, str) and prompt_raw.strip():
                try:
                    graph = json.loads(prompt_raw)
                except Exception:
                    graph = None
                if isinstance(graph, dict):
                    positive, negative = _extract_comfy_positive_negative(graph)

            if positive:
                # Keep image-like result schema for compatibility.
                return {
                    "file": rel,
                    "date": date,
                    "positive": positive,
                    "negative": negative or "",
                    "extras": {
                        "prompt_raw": prompt_raw,
                        "workflow": workflow,
                        "comment_raw": comment_raw,
                    },
                }, None

            # Backward-compat: fallback to paired PNG if exists
            pair_png = Path(file_path).with_suffix(".png")
            if pair_png.is_file():
                return extract_prompt_with_reason(pair_png)
            return None, "metadata_missing"
        except Exception as exc:
            logging.debug("Video meta parse failed for %s: %s", file_path, exc)
            pair_png = Path(file_path).with_suffix(".png")
            if pair_png.is_file():
                return extract_prompt_with_reason(pair_png)
            return None, "metadata_error"

    # PNG/image: existing logic
    data, status = parse_png_metadata_with_status(file_path)
    rel = _to_rel_file_key(file_path)
    date = _date_from_rel(rel)

    if data:
        return _build_prompt_result_from_png_data(data, rel, date), None

    png_reason = None
    if status != "ok":
        png_reason = f"png_{status}"

    meta, meta_reason = get_meta_with_retry_with_reason(file_path)
    info = extract_tags_from_meta(meta) if meta else None
    if not info:
        return None, meta_reason or png_reason or "metadata_missing"

    return _build_prompt_result_from_meta(info, meta, rel, date), None


def extract_prompt_from_file(file_path: Union[str, os.PathLike]) -> Optional[Dict]:
    info, _reason = extract_prompt_with_reason(file_path)
    return info

def extract_prompt_from_png(folder_path: Union[str, os.PathLike]) -> List[Dict]:
    folder = Path(folder_path)
    results: List[Dict] = []
    for p in folder.rglob("*.png"):
        name_lower = p.name.lower()
        if "(video)" in name_lower or name_lower.startswith("video"):
            continue
        item = extract_prompt_from_file(p)
        if item:
            results.append(item)
    return results

def get_image_date(path: Union[str, os.PathLike]) -> str:
    try:
        rel = _to_rel_file_key(path)
        d = _date_from_rel(rel, default="")
        if d and len(d) == 10 and d[4] == "-" and d[7] == "-":
            return d
        ts = os.path.getctime(path)
        return time.strftime("%Y-%m-%d", time.localtime(ts))
    except Exception:
        return "unknown"

def extract_tags(path: Union[str, os.PathLike]) -> Dict:
    item = extract_prompt_from_file(path)
    if not item:
        return {
            "positive": "",
            "negative": "",
            "tags_positive": [],
            "tags_negative": [],
            "model": "",
            "raw_prompt": "",
            "seed": None,
            "steps": None,
            "cfg": None,
            "sampler": None,
            "scheduler": None,
            "denoise": None,
            "model_checkpoint": None,
            "vae_name": None,
            "loras": None,
        }
    raw_prompt = (item.get("positive", "") or "") + (
        " Negative prompt: " + item.get("negative", "") if item.get("negative") else ""
    )
    return {
        "positive": item.get("positive", ""),
        "negative": item.get("negative", ""),
        "tags_positive": item.get("tags_positive", []),
        "tags_negative": item.get("tags_negative", []),
        "model": item.get("model", ""),
        "raw_prompt": raw_prompt,
        "seed": item.get("seed"),
        "steps": item.get("steps"),
        "cfg": item.get("cfg"),
        "sampler": item.get("sampler"),
        "scheduler": item.get("scheduler"),
        "denoise": item.get("denoise"),
        "model_checkpoint": item.get("model_checkpoint"),
        "vae_name": item.get("vae_name"),
        "loras": item.get("loras"),
    }
