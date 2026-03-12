# -*- coding: utf-8 -*-
"""
ComfyUI PNG 메타데이터 범용 파서 (메뉴형)
- KSampler / KSampler Cycle (WAS) / KSamplerAdvanced / SamplerCustomAdvanced(FLUX/Nunchaku) 지원
- 드라이런, 전체 스캔→JSONL, 무결성 요약, 누락 샘플/진단 JSONL
- .env 의 DEST 를 기본 루트로 사용
"""

import os, sys, json, time, hashlib, re, zlib
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Tuple, Optional

from PIL import Image, PngImagePlugin

import settings
from core.media.thumbs import THUMB_CACHE_DIR

# ========= 설정 =========
REQUIRE_NEGATIVE_PROMPT = False     # 네거티브 프롬프트를 누락으로 볼지 여부
AGGRESSIVE_PROMPT_TRACE = True      # 프롬프트 문자열 공격적 수집
MAX_TRACE_DEPTH = 40                # 그래프 추적 깊이
PRINT_PROGRESS_EVERY = 200          # 진행로그 주기
DATE_FOLDER_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")
VIDEO_EXTS = (".mp4", ".webm", ".mov", ".avi", ".mkv", ".gif")
THUMB_DIR_NAME = Path(THUMB_CACHE_DIR).name
EXCLUDE_REASON_LABELS = {
    "failed": "failed 폴더",
    "quarantine": "격리 폴더",
    "non_date_folder": "날짜 폴더 아님",
    "hidden": "숨김",
    "thumbnail_dir": "썸네일 폴더",
    "non_png": "PNG 아님",
    "read_failed": "읽기 실패",
}
SCAN_GAP_REASON_LABELS = {
    "cancelled": "취소됨",
    "limit_reached": "limit 도달",
}
SCAN_STOP_REASON_LABELS = {
    "cancelled": "취소됨",
    "limit_reached": "limit 도달",
}

# ========= 유틸 =========
def now_str() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")

def ensure_parent(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)

def ask_int(msg: str, default: int) -> int:
    s = input(f"{msg} (기본 {default}): ").strip()
    if not s: return default
    try:
        return int(s)
    except:
        return default

def sha256_file(p: Path, block=1024*1024) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        while True:
            b = f.read(block)
            if not b: break
            h.update(b)
    return h.hexdigest()

def read_env_root(prefer_settings: bool = True) -> Path:
    if prefer_settings and settings.DEST:
        return Path(settings.DEST)
    dest = os.getenv("DEST")
    if not dest:
        # fallback: ComfyUI output/Sorted_by_Date 안쓰는 경우도 대비
        dest = os.getenv("SOURCE") or ""
    return Path(dest) if dest else Path.cwd()

# ========= PNG 메타 로드 =========
def _read_png_text_chunks(png: Path) -> Dict[str, str]:
    texts: Dict[str, str] = {}
    try:
        with png.open("rb") as f:
            signature = f.read(8)
            if signature != b"\x89PNG\r\n\x1a\n":
                return texts
            while True:
                length_bytes = f.read(4)
                if len(length_bytes) != 4:
                    break
                length = int.from_bytes(length_bytes, "big")
                chunk_type = f.read(4)
                if len(chunk_type) != 4:
                    break
                data = f.read(length)
                f.read(4)  # CRC
                if chunk_type == b"tEXt":
                    if b"\x00" not in data:
                        continue
                    keyword, text_bytes = data.split(b"\x00", 1)
                    try:
                        key = keyword.decode("latin-1")
                        text = text_bytes.decode("latin-1")
                    except Exception:
                        continue
                    if key and key not in texts:
                        texts[key] = text
                elif chunk_type == b"iTXt":
                    if b"\x00" not in data:
                        continue
                    keyword, rest = data.split(b"\x00", 1)
                    if len(rest) < 2:
                        continue
                    compression_flag = rest[0]
                    rest = rest[2:]  # skip compression flag + method
                    try:
                        lang, rest = rest.split(b"\x00", 1)
                        translated, text_bytes = rest.split(b"\x00", 1)
                    except ValueError:
                        continue
                    try:
                        if compression_flag == 1:
                            text_bytes = zlib.decompress(text_bytes)
                        key = keyword.decode("latin-1")
                        text = text_bytes.decode("utf-8")
                    except Exception:
                        continue
                    if key and key not in texts:
                        texts[key] = text
                if chunk_type == b"IEND":
                    break
    except Exception:
        return texts
    return texts

def load_prompt_json(
    png: Path,
) -> Tuple[
    Optional[Dict[str, Any]],
    Optional[Dict[str, Any]],
    Optional[Dict[str, Any]],
    str,
    Dict[str, Optional[str]],
]:
    """
    PNG에서 ComfyUI Prompt/Workflow JSON을 로드
    return: (prompt_api_dict, workflow_dict, prompt_dict)
    """
    try:
        with Image.open(png) as im:
            info = im.info or {}
    except Exception:
        return None, None, None, "read_failed", {
            "Prompt": None,
            "Workflow": None,
            "parameters": None,
        }

    # ComfyUI는 보통 'prompt' 또는 'Prompt' 키에 JSON 저장
    raw_prompt = info.get("prompt") or info.get("Prompt")
    raw_parameters = info.get("parameters")
    raw_workflow = info.get("workflow") or info.get("Workflow")
    if not raw_prompt or not raw_workflow or not raw_parameters:
        text_chunks = _read_png_text_chunks(png)
        if not raw_prompt:
            raw_prompt = text_chunks.get("Prompt") or text_chunks.get("prompt")
        if not raw_parameters:
            raw_parameters = text_chunks.get("parameters") or text_chunks.get("Parameters")
        if not raw_workflow:
            raw_workflow = text_chunks.get("Workflow") or text_chunks.get("workflow")

    prompt_json = _maybe_parse_json(raw_prompt)
    parameters_json = _maybe_parse_json(raw_parameters)
    workflow_json = _maybe_parse_json(raw_workflow)
    if prompt_json is None and parameters_json is not None:
        prompt_json = parameters_json
    if prompt_json is None and workflow_json is None:
        status = "parse_failed" if any([raw_prompt, raw_parameters, raw_workflow]) else "no_meta"
        return None, None, None, status, {
            "Prompt": raw_prompt,
            "Workflow": raw_workflow,
            "parameters": raw_parameters,
        }

    if prompt_json and "nodes" in prompt_json and workflow_json is None:
        workflow_json = prompt_json
    api = prompt_json or workflow_json
    return api, workflow_json, prompt_json, "ok", {
        "Prompt": raw_prompt,
        "Workflow": raw_workflow,
        "parameters": raw_parameters,
    }

def build_nodes_dict(api: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    # ComfyUI Prompt는 { "node_id": { "class_type": .., "inputs": .., "_meta": .. }, ... } 형태가 많음
    if "nodes" in api and isinstance(api["nodes"], list):
        # workflow 형식
        nodes = {}
        for nd in api["nodes"]:
            nid = str(nd.get("id"))
            ndict = {
                "class_type": nd.get("type"),
                "inputs": {},
                "_meta": nd.get("_meta") or {},
            }
            # 연결은 "links" 별도로 있으나, 대부분 inputs->link 매핑은 상위 JSON(별도)로 필요.
            # Comfy가 PNG에 저장하는 Prompt(JSON) 형식은 보통 api dict 스타일이므로,
            # workflow-only인 경우엔 아래 파서가 제한적일 수 있음.
            # (실전에서는 api dict 스타일이 대부분)
            nodes[nid] = ndict
        return nodes
    # api dict 스타일
    nodes: Dict[str, Dict[str, Any]] = {}
    for nid, nd in api.items():
        if not isinstance(nd, dict): 
            continue
        n = {
            "class_type": nd.get("class_type") or nd.get("type") or "",
            "inputs": nd.get("inputs") or {},
            "_meta": nd.get("_meta") or {},
        }
        nodes[str(nid)] = n
    return nodes

def _maybe_parse_json(value: Any) -> Optional[Dict[str, Any]]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            return None
        if isinstance(parsed, dict):
            return parsed
    return None

def parse_prompt_json_strings(
    prompt_value: Any,
    workflow_value: Any,
    parameters_value: Any,
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    prompt_json = _maybe_parse_json(prompt_value)
    parameters_json = _maybe_parse_json(parameters_value)
    workflow_json = _maybe_parse_json(workflow_value)
    if prompt_json is None and parameters_json is not None:
        prompt_json = parameters_json
    if prompt_json and "nodes" in prompt_json and workflow_json is None:
        workflow_json = prompt_json
    api = prompt_json or workflow_json
    return api, workflow_json, prompt_json

def _collect_nodes_from_data(data: Any, seen: Optional[set] = None) -> List[Dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    if seen is None:
        seen = set()
    obj_id = id(data)
    if obj_id in seen:
        return []
    seen.add(obj_id)
    nodes: List[Dict[str, Any]] = []
    raw_nodes = data.get("nodes")
    if isinstance(raw_nodes, list):
        nodes.extend([n for n in raw_nodes if isinstance(n, dict)])
    else:
        nodes.extend([n for n in data.values() if isinstance(n, dict)])
    for key in ("Prompt", "Workflow", "prompt", "workflow"):
        if key in data:
            nested = _maybe_parse_json(data.get(key))
            if isinstance(nested, dict):
                nodes.extend(_collect_nodes_from_data(nested, seen))
    return nodes

def _node_type_value(node: Dict[str, Any]) -> str:
    return (node.get("class_type") or node.get("type") or "").lower()

def _normalize_node_type(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())

def _extract_workflow_nodes(wf: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not isinstance(wf, dict):
        return []
    nodes = wf.get("nodes")
    if isinstance(nodes, list):
        return [node for node in nodes if isinstance(node, dict)]
    return []

def get_node(nodes: Dict[str, Dict[str, Any]], ref) -> Optional[Dict[str, Any]]:
    if isinstance(ref, list) and ref:
        rid = str(ref[0])
        return nodes.get(rid)
    if isinstance(ref, (str, int)):
        return nodes.get(str(ref))
    return None

def _iter_node_refs(val):
    if isinstance(val, list) and val:
        fst = val[0]
        if isinstance(fst, (str, int)):
            yield str(fst)
        for item in val:
            if isinstance(item, list) and item:
                f = item[0]
                if isinstance(f, (str, int)):
                    yield str(f)

# ========= 노드 타입 체크 =========
def is_ksampler_like(n: Dict[str, Any]) -> bool:
    ct = (n.get("class_type") or "").lower()
    return ct in {"ksampler", "ksampler cycle", "ksampler cycle kj"} or "ksampler cycle" in ct

def is_ksampler_advanced(n: Dict[str, Any]) -> bool:
    ct = (n.get("class_type") or "").lower()
    return ct == "ksampleradvanced" or "ksampler advanced" in ct

def is_flux_sampler(n: Dict[str, Any]) -> bool:
    ct = (n.get("class_type") or "").lower()
    return "samplercustomadvanced" in ct  # FLUX/Nunchaku

def is_basic_guider(n: Dict[str, Any]) -> bool:
    ct = (n.get("class_type") or "").lower()
    return ct == "basicguider" or ct.endswith("guider")

def is_flux_guidance(n: Dict[str, Any]) -> bool:
    return "fluxguidance" in (n.get("class_type") or "").lower()

def is_ksampler_select(n: Dict[str, Any]) -> bool:
    return "ksamplerselect" in (n.get("class_type") or "").lower()

def is_basic_scheduler(n: Dict[str, Any]) -> bool:
    return (n.get("class_type") or "").lower() == "basicscheduler"

def is_random_noise(n: Dict[str, Any]) -> bool:
    return (n.get("class_type") or "").lower() == "randomnoise"

def is_nunchaku_dit_loader(n: Dict[str, Any]) -> bool:
    return "nunchakufluxditloader" in (n.get("class_type") or "").lower()

def is_nunchaku_lora_loader(n: Dict[str, Any]) -> bool:
    return "nunchakufluxloraloader" in (n.get("class_type") or "").lower()

def is_vae_loader(n: Dict[str, Any]) -> bool:
    return (n.get("class_type") or "").lower() == "vaeloader"

# ========= 프롬프트 수집 =========
TEXT_KEYS = {
    "text", "text_g", "text_l",
    "prompt", "caption", "style", "style_positive", "style_negative",
    "add_text", "extra", "prepend", "append",
    "a", "b", "c", "d",
    "pos", "neg", "string", "value", "desc", "description", "tag", "tags"
}
FILELIKE_EXTS = (".safetensors", ".ckpt", ".pt", ".pth", ".bin", ".yaml", ".yml", ".json")

def _looks_like_path(s: str) -> bool:
    return ("\\" in s) or ("/" in s) or (":\\" in s.lower())

def _is_windows_drive_path(s: str) -> bool:
    return len(s) >= 3 and s[1] == ":" and s[2] in {"\\", "/"}

def _is_probable_prompt_string(s: str, allow_plain: bool = False) -> bool:
    """
    프롬프트로 보이는 텍스트를 판별한다.
    - allow_plain=True: TEXT 키와 같이 순수 한 단어 프롬프트도 허용
    - allow_plain=False: 구분자(공백/콤마/개행 등)나 embedding: 접두가 있을 때만 허용
    """
    if not s or not isinstance(s, str):
        return False
    t = s.strip()
    if len(t) <= 1:
        return False
    if t.isdigit():
        return False

    lower_t = t.lower()
    embedding_like = lower_t.startswith("embedding:") and len(t) > len("embedding:")
    has_mixed_delimiters = (
        any(ch in t for ch in [" ", ",", ";", "|", "\n"]) or
        (":" in t and not _is_windows_drive_path(t))
    )

    if any(lower_t.endswith(ext) for ext in FILELIKE_EXTS):
        if embedding_like or has_mixed_delimiters:
            return True
        return False

    if _looks_like_path(t):
        if embedding_like or has_mixed_delimiters:
            return True
        return False

    if not (embedding_like or has_mixed_delimiters):
        return allow_plain
    return True


def _is_probable_pathish_text(s: str) -> bool:
    if not s or not isinstance(s, str):
        return False
    lower = s.lower()
    if any(lower.endswith(ext) for ext in FILELIKE_EXTS):
        return True
    if _looks_like_path(s) or "->" in s or "→" in s:
        return True
    return False

def _collect_textlike_from_inputs(ins: dict) -> List[str]:
    collected: List[str] = []
    def walk(obj, key_hint=None):
        if obj is None:
            return
        if isinstance(obj, str):
            allow_plain = key_hint and key_hint in TEXT_KEYS
            if not allow_plain and _is_probable_pathish_text(obj):
                return
            if (allow_plain and _is_probable_prompt_string(obj, allow_plain=True)) \
               or (AGGRESSIVE_PROMPT_TRACE and _is_probable_prompt_string(obj, allow_plain=False)):
                collected.append(obj.strip())
            return
        if isinstance(obj, dict):
            for k, v in obj.items():
                walk(v, str(k).lower())
        elif isinstance(obj, list):
            for it in obj:
                walk(it, key_hint)
    walk(ins)
    # uniq
    seen, uniq = set(), []
    for t in collected:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq

def _filter_branch_inputs(ins: dict, branch: Optional[str]) -> dict:
    branch = (branch or "").lower()
    if branch not in {"positive", "negative"}:
        return ins
    if branch == "positive":
        keep_keys = {"positive", "pos"}
        drop_keys = {"negative", "neg"}
    else:
        keep_keys = {"negative", "neg"}
        drop_keys = {"positive", "pos"}
    has_keep = any(k in ins for k in keep_keys)
    has_drop = any(k in ins for k in drop_keys)
    if has_keep and has_drop:
        return {k: v for k, v in ins.items() if k not in drop_keys}
    return ins

def gather_texts_from_conditioning(
    nodes: dict,
    start_conn,
    max_depth: int = MAX_TRACE_DEPTH,
    branch: Optional[str] = None,
) -> Optional[str]:
    if not start_conn:
        return None
    start_ids = list(_iter_node_refs(start_conn))
    if not start_ids:
        return None
    collected: List[str] = []
    visited: set[str] = set()
    stack: List[Tuple[str, int]] = [(nid, 0) for nid in start_ids]
    while stack:
        nid, depth = stack.pop()
        if nid in visited or depth > max_depth:
            continue
        visited.add(nid)
        node = nodes.get(nid)
        if not isinstance(node, dict):
            continue
        ins = _filter_branch_inputs(node.get("inputs", {}) or {}, branch)
        for t in _collect_textlike_from_inputs(ins):
            collected.append(t)
        for v in ins.values():
            for ref_id in _iter_node_refs(v):
                if ref_id not in visited:
                    stack.append((ref_id, depth+1))
    if not collected:
        return None
    seen, uniq = set(), []
    for t in collected:
        tt = t.strip()
        if tt and tt not in seen:
            seen.add(tt)
            uniq.append(tt)

    if not uniq:
        return None

    prompt_texts = [t for t in uniq if not _is_probable_pathish_text(t)]
    pathish_texts = [t for t in uniq if _is_probable_pathish_text(t)]

    if prompt_texts:
        return " | ".join(prompt_texts)
    if pathish_texts:
        return " | ".join(pathish_texts)
    return None

def resolve_clip_text(nodes: dict, conn) -> Optional[str]:
    # 연결된 하나의 CLIPTextEncode에서 text* 키만 회수
    node = get_node(nodes, conn)
    if not node: return None
    ins = node.get("inputs", {}) or {}
    for key in ("text", "text_g", "text_l"):
        t = ins.get(key)
        if isinstance(t, str) and _is_probable_prompt_string(t, allow_plain=True):
            return t.strip()
    return None

def find_cliptext_by_meta_title(nodes: dict, keyword: str) -> Optional[str]:
    texts: List[str] = []
    for n in nodes.values():
        ct = (n.get("class_type") or "").lower()
        if "cliptextencode" in ct:
            title = str(((n.get("_meta") or {}).get("title")) or "")
            if keyword.lower() in title.lower():
                ins = n.get("inputs", {}) or {}
                t = ins.get("text") or ins.get("text_g") or ins.get("text_l")
                if isinstance(t, str) and _is_probable_prompt_string(t, allow_plain=True):
                    texts.append(t.strip())
    if not texts: return None
    return " | ".join(list(dict.fromkeys(texts)))

def _path_has_empty_clip_text(
    nodes: dict,
    start_conn,
    max_depth: int = MAX_TRACE_DEPTH,
    branch: Optional[str] = None,
) -> bool:
    if not start_conn: return False
    start_ids = list(_iter_node_refs(start_conn))
    if not start_ids: return False
    visited = set()
    stack = [(nid, 0) for nid in start_ids]
    while stack:
        nid, depth = stack.pop()
        if nid in visited or depth > max_depth: continue
        visited.add(nid)
        node = nodes.get(nid)
        if not isinstance(node, dict): continue
        ct = (node.get("class_type") or "").lower()
        ins = _filter_branch_inputs(node.get("inputs", {}) or {}, branch)
        if "cliptextencode" in ct:
            for key in ("text", "text_g", "text_l"):
                if key in ins and isinstance(ins[key], str):
                    if ins[key].strip() == "":
                        return True
        for v in ins.values():
            for ref_id in _iter_node_refs(v):
                if ref_id not in visited:
                    stack.append((ref_id, depth+1))
    return False

def _path_contains_conditioning_zero_out(
    nodes: dict,
    start_conn,
    max_depth: int = MAX_TRACE_DEPTH,
    branch: Optional[str] = None,
) -> bool:
    if not start_conn: return False
    start_ids = list(_iter_node_refs(start_conn))
    if not start_ids: return False
    visited: set[str] = set()
    stack: List[Tuple[str, int]] = [(nid, 0) for nid in start_ids]
    while stack:
        nid, depth = stack.pop()
        if nid in visited or depth > max_depth:
            continue
        visited.add(nid)
        node = nodes.get(nid)
        if not isinstance(node, dict):
            continue
        ct = (node.get("class_type") or "").lower()
        if "conditioningzeroout" in ct:
            return True
        ins = _filter_branch_inputs(node.get("inputs", {}) or {}, branch)
        for v in ins.values():
            for ref_id in _iter_node_refs(v):
                if ref_id not in visited:
                    stack.append((ref_id, depth+1))
    return False

# ========= Sampler 파싱 =========
def _resolve_input_value(nodes: dict, value: Any, keys: Tuple[str, ...]) -> Any:
    if isinstance(value, list) and value:
        n = nodes.get(str(value[0]))
        if n:
            ni = n.get("inputs", {}) or {}
            for key in keys:
                if key in ni:
                    return ni[key]
    return value

def _coerce_sampler_value(value: Any, *, kind: Optional[str] = None) -> Any:
    if value is None:
        return None
    try:
        if kind == "int":
            return int(value)
        if kind == "float":
            return float(value)
    except (TypeError, ValueError):
        return value
    return value

def resolve_sampler_inputs(nodes: dict, node: dict) -> dict:
    ins = node.get("inputs", {}) or {}
    seed = _resolve_input_value(nodes, ins.get("seed") or ins.get("noise_seed"), ("value", "seed", "noise_seed"))
    steps = _resolve_input_value(nodes, ins.get("steps"), ("value", "steps"))
    cfg = _resolve_input_value(nodes, ins.get("cfg") or ins.get("cfg_scale"), ("value", "cfg", "cfg_scale"))
    sampler = _resolve_input_value(nodes, ins.get("sampler_name"), ("value", "sampler_name"))
    scheduler = _resolve_input_value(nodes, ins.get("scheduler"), ("value", "scheduler"))
    denoise = _resolve_input_value(nodes, ins.get("denoise"), ("value", "denoise"))
    return {
        "seed": _coerce_sampler_value(seed, kind="int"),
        "steps": _coerce_sampler_value(steps, kind="int"),
        "cfg": _coerce_sampler_value(cfg, kind="float"),
        "sampler": sampler,
        "scheduler": scheduler,
        "denoise": _coerce_sampler_value(denoise, kind="float"),
    }

def resolve_standard_ksampler(nodes: dict, ks: dict) -> dict:
    ins = ks.get("inputs", {}) or {}
    def rc(v):
        # resolve constant or return raw
        if isinstance(v, list) and v:
            n = nodes.get(str(v[0]))
            if n:
                ni = n.get("inputs", {}) or {}
                for k in ("value","seed","steps","cfg"):
                    if k in ni: return ni[k]
        return v
    seed = rc(ins.get("seed"))
    steps = rc(ins.get("steps"))
    cfg = rc(ins.get("cfg")) or rc(ins.get("cfg_scale"))
    sampler = rc(ins.get("sampler_name"))
    scheduler = rc(ins.get("scheduler"))
    denoise = rc(ins.get("denoise"))
    # cast
    try: seed = int(seed)
    except: pass
    try: steps = int(steps)
    except: pass
    try: cfg = float(cfg)
    except: pass
    try: denoise = float(denoise)
    except: pass
    return {
        "seed": seed, "steps": steps, "cfg": cfg,
        "sampler": sampler, "scheduler": scheduler, "denoise": denoise
    }

def resolve_kcycle_extras(nodes: dict, ks: dict) -> dict:
    # WAS KSampler Cycle 확장 필드
    ins = ks.get("inputs", {}) or {}
    get = lambda k: ins.get(k)
    def rc(v):
        if isinstance(v, list) and v:
            n = nodes.get(str(v[0])); 
            if n: 
                ni = n.get("inputs", {}) or {}
                if "value" in ni: return ni["value"]
        return v
    extras = {
        "upscale_factor": rc(get("upscale_factor")),
        "upscale_cycles": rc(get("upscale_cycles")),
        "starting_denoise": rc(get("starting_denoise")),
        "cycle_denoise": rc(get("cycle_denoise")),
        "scale_denoise": rc(get("scale_denoise")),
        "latent_upscale": rc(get("latent_upscale")),
        "scale_sampling": rc(get("scale_sampling")),
        "secondary_model": None,
        "secondary_start_cycle": rc(get("secondary_start_cycle")),
        "upscale_model": None,
        "processor_model": None,
        "steps_scaling": rc(get("steps_scaling")),
        "steps_control": rc(get("steps_control")),
        "steps_scaling_value": rc(get("steps_scaling_value")),
        "steps_cutoff": rc(get("steps_cutoff")),
        "denoise_cutoff": rc(get("denoise_cutoff")),
    }
    # 연결된 모델명/업스케일러 이름 회수 시도
    if isinstance(get("upscale_model"), list):
        nm = nodes.get(str(get("upscale_model")[0]))
        if nm:
            name = (nm.get("inputs", {}) or {}).get("model_name")
            extras["upscale_model"] = name
    if isinstance(get("model"), list):
        # secondary_model이 따로 있을 수 있음
        pass
    return extras

def _trace_flux_guidance_value(nodes: dict, start_conn) -> Optional[Any]:
    if start_conn is None:
        return None
    if isinstance(start_conn, (int, float, str)):
        return start_conn
    start_ids = list(_iter_node_refs(start_conn))
    if not start_ids:
        return None
    visited: set[str] = set()
    stack: List[str] = list(start_ids)
    while stack:
        nid = stack.pop()
        if nid in visited:
            continue
        visited.add(nid)
        node = nodes.get(str(nid))
        if not isinstance(node, dict):
            continue
        if is_flux_guidance(node):
            return (node.get("inputs", {}) or {}).get("guidance")
        for v in (node.get("inputs", {}) or {}).values():
            for rid in _iter_node_refs(v):
                if rid not in visited:
                    stack.append(rid)
    return None

def resolve_flux_bundle(nodes: dict, flux_node: dict) -> dict:
    out = {
        "seed": None, "sampler": None, "steps": None, "scheduler": None, "denoise": None,
        "positive_prompt": None, "negative_prompt": None, "guidance": None,
        "model_checkpoint": None, "vae_name": None,
        "text_encoder1": None, "text_encoder2": None, "model_type": None,
    }
    fi = flux_node.get("inputs", {}) or {}

    # sampler / scheduler / seed
    sref = fi.get("sampler"); sn = get_node(nodes, sref)
    if sn and is_ksampler_select(sn):
        out["sampler"] = (sn.get("inputs", {}) or {}).get("sampler_name")

    sigref = fi.get("sigmas"); sgn = get_node(nodes, sigref)
    if sgn and is_basic_scheduler(sgn):
        sin = sgn.get("inputs", {}) or {}
        out["steps"] = sin.get("steps")
        out["scheduler"] = sin.get("scheduler")
        out["denoise"] = sin.get("denoise")

    nref = fi.get("noise"); nn = get_node(nodes, nref)
    if nn and is_random_noise(nn):
        out["seed"] = (nn.get("inputs", {}) or {}).get("noise_seed")

    # guider -> conditioning -> prompt
    gref = fi.get("guider"); gn = get_node(nodes, gref)
    if gn:
        gin = gn.get("inputs", {}) or {}
        cond = gin.get("conditioning")
        pos_conn = gin.get("positive") or cond
        neg_conn = gin.get("negative")

        if out["positive_prompt"] is None:
            out["positive_prompt"] = (
                gather_texts_from_conditioning(nodes, pos_conn or cond, branch="positive")
                or resolve_clip_text(nodes, pos_conn or cond)
                or find_cliptext_by_meta_title(nodes, "Text Encode")
                or find_cliptext_by_meta_title(nodes, "Positive")
            )
        if out["negative_prompt"] is None:
            out["negative_prompt"] = (
                gather_texts_from_conditioning(nodes, neg_conn, branch="negative")
                or resolve_clip_text(nodes, neg_conn)
                or find_cliptext_by_meta_title(nodes, "Negative")
            )
        if _path_contains_conditioning_zero_out(nodes, neg_conn, branch="negative"):
            out["negative_prompt"] = "ConditioningZeroOut"
        if out["guidance"] is None:
            cfg_val = gin.get("cfg")
            out["guidance"] = (
                cfg_val
                if cfg_val is not None
                else _trace_flux_guidance_value(nodes, gin.get("guidance") or cond)
            )
        # model path
        mref = gin.get("model"); mn = get_node(nodes, mref)
        if mn and is_nunchaku_lora_loader(mn):
            m2 = get_node(nodes, (mn.get("inputs", {}) or {}).get("model"))
            if m2 and is_nunchaku_dit_loader(m2):
                out["model_checkpoint"] = (m2.get("inputs", {}) or {}).get("model_path")
        elif mn and is_nunchaku_dit_loader(mn):
            out["model_checkpoint"] = (mn.get("inputs", {}) or {}).get("model_path")

    # VAE / 텍스트 인코더
    for n in nodes.values():
        if is_vae_loader(n):
            vn = (n.get("inputs", {}) or {}).get("vae_name")
            if isinstance(vn, str) and vn:
                out["vae_name"] = vn
                break
    for n in nodes.values():
        ct = (n.get("class_type") or "").lower()
        if "nunchakutextencoderloaderv2" in ct:
            ins = n.get("inputs", {}) or {}
            out["text_encoder1"] = ins.get("text_encoder1")
            out["text_encoder2"] = ins.get("text_encoder2")
            out["model_type"] = ins.get("model_type")
            break
    return out

def resolve_ksampler_advanced_chain(nodes: dict, final_id: str) -> dict:
    """
    KSamplerAdvanced 체인(High/Low 등 분할) 파싱
    - steps 총합 및 분할 단계 길이
    - cfg (단일 또는 분할별 목록)
    - seed (첫 세그먼트의 noise_seed/seed)
    - sampler/scheduler (마지막 노드 기준)
    - prompt: 마지막 노드의 positive/negative 입력 경로 추적
    """
    # 체인 역추적
    chain: List[str] = []
    cur = final_id
    while True:
        nd = nodes.get(cur)
        if not nd or not is_ksampler_advanced(nd):
            break
        chain.insert(0, cur)
        prev = nd.get("inputs", {}).get("latent_image")
        if prev:
            pid = str(prev[0])
            pn = nodes.get(pid)
            if pn and is_ksampler_advanced(pn):
                cur = pid
                continue
        break
    if not chain:
        chain = [final_id]
    # 총 steps
    def rc_const(v):
        if isinstance(v, list) and v:
            n = nodes.get(str(v[0]))
            if n:
                ni = n.get("inputs", {}) or {}
                if "value" in ni: return ni["value"]
                if "steps" in ni: return ni["steps"]
        return v
    last = nodes[chain[-1]]
    total_steps = rc_const(last.get("inputs", {}).get("steps"))
    try: total_steps = int(total_steps)
    except: total_steps = None
    # 분할 길이 & CFG
    seg_lengths: List[int] = []
    cfg_vals: List[Any] = []
    for sid in chain:
        n = nodes[sid]; ins = n.get("inputs", {}) or {}
        start = rc_const(ins.get("start_at_step"))
        end   = rc_const(ins.get("end_at_step"))
        try:
            start_i = int(start) if start is not None else 0
        except: start_i = 0
        try:
            end_i = int(end) if end is not None else total_steps
        except: end_i = total_steps
        if end_i is not None and start_i is not None and end_i > start_i:
            seg_lengths.append(end_i - start_i)
        cfg = rc_const(ins.get("cfg"))
        if cfg is not None: cfg_vals.append(cfg)
    if total_steps is None and seg_lengths:
        total_steps = sum(seg_lengths)
    # sampler/scheduler
    sname = last.get("inputs", {}).get("sampler_name")
    sched = last.get("inputs", {}).get("scheduler")
    if isinstance(sname, list): sname = None
    if isinstance(sched, list): sched = None
    # seed: 첫 세그먼트의 noise_seed/seed
    first = nodes[chain[0]]; fins = first.get("inputs", {}) or {}
    seed = fins.get("noise_seed") or fins.get("seed")
    if isinstance(seed, list):
        nid = str(seed[0]); n = nodes.get(nid)
        if n:
            ni = n.get("inputs", {}) or {}
            seed = ni.get("value") or ni.get("seed")
    try:
        seed = int(seed)
    except:
        pass
    # prompt: 마지막 노드의 positive/negative 경로 추적
    pos = last.get("inputs", {}).get("positive")
    neg = last.get("inputs", {}).get("negative")
    pos_text = gather_texts_from_conditioning(nodes, pos, branch="positive") or resolve_clip_text(nodes, pos)
    neg_text = gather_texts_from_conditioning(nodes, neg, branch="negative") or resolve_clip_text(nodes, neg)
    neg_zeroed = _path_contains_conditioning_zero_out(nodes, neg, branch="negative")
    if neg_zeroed:
        neg_text = "ConditioningZeroOut"
    if pos_text is None and _path_has_empty_clip_text(nodes, pos, branch="positive"): pos_text = ""
    if not neg_zeroed and neg_text is None and _path_has_empty_clip_text(nodes, neg, branch="negative"): neg_text = ""
    return {
        "seed": seed, "steps": total_steps, "segments": seg_lengths or None,
        "cfg": cfg_vals or None, "sampler": sname, "scheduler": sched,
        "positive_prompt": pos_text, "negative_prompt": neg_text,
    }

# ========= 메인 파서 =========
def parse_png(png: Path) -> Tuple[Dict[str, Any], str]:
    api, wf, prompt_json, status, raw_meta = load_prompt_json(png)
    base_result = {
        "Prompt_raw": raw_meta.get("Prompt"),
        "Workflow_raw": raw_meta.get("Workflow"),
        "parameters_raw": raw_meta.get("parameters"),
    }
    if status != "ok":
        return base_result, status
    nodes = build_nodes_dict(api)
    if not nodes:
        return base_result, "no_nodes"

    # 0) 이미지 크기/시간
    try:
        with Image.open(png) as im:
            width, height = im.size
    except Exception:
        width = height = None
    try:
        created = datetime.fromtimestamp(png.stat().st_mtime).isoformat()
    except Exception:
        created = None
    wf_id = None
    if isinstance(wf, dict):
        wf_id = wf.get("id")
    node_count = len(nodes)
    # 1) VAEDecode -> samples 연결 따라 최종 sampler 후보 찾기
    final_sampler_id = None
    for nid, n in nodes.items():
        if (n.get("class_type") or "").lower().startswith("vaedecode"):
            sin = (n.get("inputs", {}) or {}).get("samples")
            if sin:
                final_sampler_id = str(sin[0])
                break
    # SaveImage가 바로 latent를 받을 수도 있음
    if not final_sampler_id:
        for nid, n in nodes.items():
            if (n.get("class_type") or "").lower().startswith("saveimage"):
                img_in = (n.get("inputs", {}) or {}).get("images") or (n.get("inputs", {}) or {}).get("image")
                if img_in:
                    src = nodes.get(str(img_in[0]))
                    if src and (src.get("class_type") or "").lower().startswith("vaedecode"):
                        sin = (src.get("inputs", {}) or {}).get("samples")
                        if sin: final_sampler_id = str(sin[0]); break
                    else:
                        final_sampler_id = str(img_in[0]); break

    # 2) 우선순위로 판별
    # 2-1) 최종이 KSamplerAdvanced?
    if final_sampler_id and final_sampler_id in nodes and is_ksampler_advanced(nodes[final_sampler_id]):
        adv = resolve_ksampler_advanced_chain(nodes, final_sampler_id)
        # sampler info
        seed = adv.get("seed"); steps = adv.get("steps"); cfg = adv.get("cfg")
        sampler = adv.get("sampler"); scheduler = adv.get("scheduler")
        denoise = None
        pos_text = adv.get("positive_prompt"); neg_text = adv.get("negative_prompt")
        # 모델/LoRA/vae 스캔(전역)
        models, vae_name, loras = scan_models_loras(nodes)
        model_checkpoint = models[0] if models else None
        result = {
            "file": str(png), "width": width, "height": height, "created": created,
            "seed": seed, "steps": steps, "cfg": cfg, "sampler": sampler, "scheduler": scheduler,
            "denoise": denoise, "positive_prompt": pos_text, "negative_prompt": neg_text,
            "model_checkpoint": model_checkpoint, "models": models, "loras": loras or None,
            "workflow_id": wf_id, "node_count": node_count, "vae_name": vae_name,
        }
        result.update(base_result)
        if prompt_json is not None:
            result["Prompt"] = prompt_json
        if wf is not None:
            result["Workflow"] = wf
        return result, "ok"

    # 2-2) 표준 KSampler / KSampler Cycle
    ks = None
    ks_id = None
    for nid, n in nodes.items():
        if is_ksampler_like(n):
            ks = n; ks_id = nid; break
    if ks:
        info = resolve_standard_ksampler(nodes, ks)
        pos = (ks.get("inputs", {}) or {}).get("positive")
        neg = (ks.get("inputs", {}) or {}).get("negative")
        pos_text = gather_texts_from_conditioning(nodes, pos, branch="positive") or resolve_clip_text(nodes, pos) or find_cliptext_by_meta_title(nodes, "Positive")
        neg_text = gather_texts_from_conditioning(nodes, neg, branch="negative") or resolve_clip_text(nodes, neg) or find_cliptext_by_meta_title(nodes, "Negative")
        neg_zeroed = _path_contains_conditioning_zero_out(nodes, neg, branch="negative")
        if neg_zeroed:
            neg_text = "ConditioningZeroOut"
        if pos_text is None and _path_has_empty_clip_text(nodes, pos, branch="positive"): pos_text = ""
        if not neg_zeroed and neg_text is None and _path_has_empty_clip_text(nodes, neg, branch="negative"): neg_text = ""
        extras = {}
        if "cycle" in (ks.get("class_type") or "").lower():
            extras = resolve_kcycle_extras(nodes, ks)
        models, vae_name, loras = scan_models_loras(nodes)
        model_checkpoint = models[0] if models else None
        result = {
            "file": str(png), "width": width, "height": height, "created": created,
            "seed": info.get("seed"), "steps": info.get("steps"), "cfg": info.get("cfg"),
            "sampler": info.get("sampler"), "scheduler": info.get("scheduler"),
            "denoise": info.get("denoise"), "positive_prompt": pos_text, "negative_prompt": neg_text,
            "model_checkpoint": model_checkpoint, "models": models, "loras": loras or None,
            "workflow_id": wf_id, "node_count": node_count, "vae_name": vae_name, **extras
        }
        result.update(base_result)
        if prompt_json is not None:
            result["Prompt"] = prompt_json
        if wf is not None:
            result["Workflow"] = wf
        return result, "ok"

    # 2-3) FLUX/Nunchaku (SamplerCustomAdvanced 허브)
    flux = None
    for _, n in nodes.items():
        if is_flux_sampler(n):
            flux = n; break
    if flux:
        bundle = resolve_flux_bundle(nodes, flux)
        models, vae_name2, loras = scan_models_loras(nodes)
        bundle_checkpoint = bundle.get("model_checkpoint")
        if bundle_checkpoint and bundle_checkpoint not in models:
            models = [bundle_checkpoint, *models]
        model_checkpoint = bundle_checkpoint or (models[0] if models else None)
        # guidance를 cfg처럼 취급하되, 별도 필드로도 보관
        result = {
            "file": str(png), "width": width, "height": height, "created": created,
            "seed": bundle.get("seed"), "steps": bundle.get("steps"),
            "cfg": bundle.get("guidance"), "sampler": bundle.get("sampler"),
            "scheduler": bundle.get("scheduler"), "denoise": bundle.get("denoise"),
            "positive_prompt": bundle.get("positive_prompt"), "negative_prompt": bundle.get("negative_prompt"),
            "model_checkpoint": model_checkpoint,
            "models": models, "loras": loras or None, "workflow_id": wf_id, "node_count": node_count,
            "guidance": bundle.get("guidance"), "vae_name": bundle.get("vae_name") or vae_name2,
            "text_encoder1": bundle.get("text_encoder1"), "text_encoder2": bundle.get("text_encoder2"),
            "model_type": bundle.get("model_type"),
        }
        result.update(base_result)
        if prompt_json is not None:
            result["Prompt"] = prompt_json
        if wf is not None:
            result["Workflow"] = wf
        return result, "ok"

    return base_result, "no_ksampler"


def parse_comfy_payload(
    prompt_value: Any,
    workflow_value: Any = None,
    parameters_value: Any = None,
    *,
    file: Optional[str] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    created: Optional[str] = None,
) -> Tuple[Dict[str, Any], str]:
    prompt_json = _maybe_parse_json(prompt_value)
    parameters_json = _maybe_parse_json(parameters_value)
    workflow_json = _maybe_parse_json(workflow_value)
    if prompt_json is None and parameters_json is not None:
        prompt_json = parameters_json

    raw_prompt = prompt_value
    raw_workflow = workflow_value
    raw_parameters = parameters_value
    base_result = {
        "Prompt_raw": raw_prompt,
        "Workflow_raw": raw_workflow,
        "parameters_raw": raw_parameters,
    }

    if prompt_json is None and workflow_json is None:
        status = "parse_failed" if any([raw_prompt, raw_parameters, raw_workflow]) else "no_meta"
        return base_result, status

    if prompt_json and "nodes" in prompt_json and workflow_json is None:
        workflow_json = prompt_json
    api = prompt_json or workflow_json
    if not isinstance(api, dict):
        return base_result, "parse_failed"

    nodes = build_nodes_dict(api)
    if not nodes:
        return base_result, "no_nodes"

    wf_id = None
    if isinstance(workflow_json, dict):
        wf_id = workflow_json.get("id")
    node_count = len(nodes)
    final_sampler_id = None
    for nid, n in nodes.items():
        if (n.get("class_type") or "").lower().startswith("vaedecode"):
            sin = (n.get("inputs", {}) or {}).get("samples")
            if sin:
                final_sampler_id = str(sin[0])
                break
    if not final_sampler_id:
        for nid, n in nodes.items():
            if (n.get("class_type") or "").lower().startswith("saveimage"):
                img_in = (n.get("inputs", {}) or {}).get("images") or (n.get("inputs", {}) or {}).get("image")
                if img_in:
                    src = nodes.get(str(img_in[0]))
                    if src and (src.get("class_type") or "").lower().startswith("vaedecode"):
                        sin = (src.get("inputs", {}) or {}).get("samples")
                        if sin:
                            final_sampler_id = str(sin[0])
                            break
                    else:
                        final_sampler_id = str(img_in[0])
                        break

    if final_sampler_id and final_sampler_id in nodes and is_ksampler_advanced(nodes[final_sampler_id]):
        adv = resolve_ksampler_advanced_chain(nodes, final_sampler_id)
        seed = adv.get("seed")
        steps = adv.get("steps")
        cfg = adv.get("cfg")
        sampler = adv.get("sampler")
        scheduler = adv.get("scheduler")
        denoise = None
        pos_text = adv.get("positive_prompt")
        neg_text = adv.get("negative_prompt")
        models, vae_name, loras = scan_models_loras(nodes)
        model_checkpoint = models[0] if models else None
        result = {
            "file": file,
            "width": width,
            "height": height,
            "created": created,
            "seed": seed,
            "steps": steps,
            "cfg": cfg,
            "sampler": sampler,
            "scheduler": scheduler,
            "denoise": denoise,
            "positive_prompt": pos_text,
            "negative_prompt": neg_text,
            "model_checkpoint": model_checkpoint,
            "models": models,
            "loras": loras or None,
            "workflow_id": wf_id,
            "node_count": node_count,
            "vae_name": vae_name,
        }
        result.update(base_result)
        if prompt_json is not None:
            result["Prompt"] = prompt_json
        if workflow_json is not None:
            result["Workflow"] = workflow_json
        return result, "ok"

    ks = None
    for _, n in nodes.items():
        if is_ksampler_like(n):
            ks = n
            break
    if ks:
        info = resolve_standard_ksampler(nodes, ks)
        pos = (ks.get("inputs", {}) or {}).get("positive")
        neg = (ks.get("inputs", {}) or {}).get("negative")
        pos_text = gather_texts_from_conditioning(nodes, pos, branch="positive") or resolve_clip_text(nodes, pos) or find_cliptext_by_meta_title(nodes, "Positive")
        neg_text = gather_texts_from_conditioning(nodes, neg, branch="negative") or resolve_clip_text(nodes, neg) or find_cliptext_by_meta_title(nodes, "Negative")
        neg_zeroed = _path_contains_conditioning_zero_out(nodes, neg, branch="negative")
        if neg_zeroed:
            neg_text = "ConditioningZeroOut"
        if pos_text is None and _path_has_empty_clip_text(nodes, pos, branch="positive"):
            pos_text = ""
        if not neg_zeroed and neg_text is None and _path_has_empty_clip_text(nodes, neg, branch="negative"):
            neg_text = ""
        extras = {}
        if "cycle" in (ks.get("class_type") or "").lower():
            extras = resolve_kcycle_extras(nodes, ks)
        models, vae_name, loras = scan_models_loras(nodes)
        model_checkpoint = models[0] if models else None
        result = {
            "file": file,
            "width": width,
            "height": height,
            "created": created,
            "seed": info.get("seed"),
            "steps": info.get("steps"),
            "cfg": info.get("cfg"),
            "sampler": info.get("sampler"),
            "scheduler": info.get("scheduler"),
            "denoise": info.get("denoise"),
            "positive_prompt": pos_text,
            "negative_prompt": neg_text,
            "model_checkpoint": model_checkpoint,
            "models": models,
            "loras": loras or None,
            "workflow_id": wf_id,
            "node_count": node_count,
            "vae_name": vae_name,
            **extras,
        }
        result.update(base_result)
        if prompt_json is not None:
            result["Prompt"] = prompt_json
        if workflow_json is not None:
            result["Workflow"] = workflow_json
        return result, "ok"

    flux = None
    for _, n in nodes.items():
        if is_flux_sampler(n):
            flux = n
            break
    if flux:
        bundle = resolve_flux_bundle(nodes, flux)
        models, vae_name2, loras = scan_models_loras(nodes)
        bundle_checkpoint = bundle.get("model_checkpoint")
        if bundle_checkpoint and bundle_checkpoint not in models:
            models = [bundle_checkpoint, *models]
        model_checkpoint = bundle_checkpoint or (models[0] if models else None)
        result = {
            "file": file,
            "width": width,
            "height": height,
            "created": created,
            "seed": bundle.get("seed"),
            "steps": bundle.get("steps"),
            "cfg": bundle.get("guidance"),
            "sampler": bundle.get("sampler"),
            "scheduler": bundle.get("scheduler"),
            "denoise": bundle.get("denoise"),
            "positive_prompt": bundle.get("positive_prompt"),
            "negative_prompt": bundle.get("negative_prompt"),
            "model_checkpoint": model_checkpoint,
            "models": models,
            "loras": loras or None,
            "workflow_id": wf_id,
            "node_count": node_count,
            "guidance": bundle.get("guidance"),
            "vae_name": bundle.get("vae_name") or vae_name2,
            "text_encoder1": bundle.get("text_encoder1"),
            "text_encoder2": bundle.get("text_encoder2"),
            "model_type": bundle.get("model_type"),
        }
        result.update(base_result)
        if prompt_json is not None:
            result["Prompt"] = prompt_json
        if workflow_json is not None:
            result["Workflow"] = workflow_json
        return result, "ok"

    return base_result, "no_ksampler"


def _basename_only(value: Optional[str]) -> Optional[str]:
    if not value:
        return value
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("\\", "/")
    return text.rsplit("/", 1)[-1]


def scan_models_loras(nodes: dict) -> Tuple[List[str], Optional[str], List[dict]]:
    models: List[str] = []
    vae_name = None
    loras: List[dict] = []
    def _add_model(name: Optional[str]) -> None:
        name = _basename_only(name)
        if not name:
            return
        if name not in models:
            models.append(name)
    def _scan_widgets_values(node: dict) -> None:
        widgets = node.get("widgets_values") or []
        if not isinstance(widgets, list):
            return
        ct = (node.get("class_type") or "").lower()
        if ct in ("unetloader", "checkpointloadersimple", "vaeloader"):
            primary = widgets[0] if widgets else None
            if isinstance(primary, str):
                _add_model(primary)
        for value in widgets:
            if isinstance(value, str) and ".safetensors" in value.lower():
                _add_model(value)
    for n in nodes.values():
        ct = (n.get("class_type") or "").lower()
        ins = n.get("inputs", {}) or {}
        # LoRA(여러 변형)
        if "lora" in ct:
            name = ins.get("lora_name") or ins.get("model_name") or ins.get("ckpt_name")
            strength = ins.get("lora_strength") or ins.get("strength") \
                       or ins.get("strength_model") or ins.get("strength_clip")
            name = _basename_only(name)
            if name:
                loras.append({"name": name, "strength": strength})
        # Power Lora Loader
        if ct.startswith("power lora loader") or "power lora loader" in ct:
            for key, cfg in ins.items():
                if not isinstance(cfg, dict):
                    continue
                if not key.startswith("lora_"):
                    continue
                if not cfg.get("on"):
                    continue
                name = _basename_only(cfg.get("lora"))
                strength = cfg.get("strength")
                if name:
                    loras.append({"name": name, "strength": strength})
        # VAE
        if is_vae_loader(n):
            vn = ins.get("vae_name")
            if vn: vae_name = vn
        # 모델 체크포인트 (여러 로더 케이스 포괄)
        if any(key in ins for key in ("ckpt_name","ckpt_path","model_path","checkpoint_name","gguf_name")):
            name = ins.get("ckpt_name") or ins.get("ckpt_path") or ins.get("model_path") \
                   or ins.get("checkpoint_name") or ins.get("gguf_name")
            _add_model(name)
        _scan_widgets_values(n)
    return models, vae_name, loras

# ========= 스캔/출력 =========
def print_one(result: dict):
    print(json.dumps(result, ensure_ascii=False, indent=2))

def _emit(message: str, log_cb=None) -> None:
    if log_cb:
        log_cb(message)
    else:
        print(message)

def _relative_parts(path: Path, root: Path) -> Tuple[str, ...]:
    try:
        rel = path.relative_to(root)
    except ValueError:
        rel = path
    return rel.parts

def _is_hidden_path(path: Path, root: Path) -> bool:
    return any(part.startswith(".") for part in _relative_parts(path, root))

def _is_thumbnail_path(path: Path, root: Path) -> bool:
    return THUMB_DIR_NAME in _relative_parts(path, root)

def _exclude_reason(
    path: Path,
    root: Path,
    *,
    date_folder_only: bool,
    exclude_failed: bool,
    include_quarantine: bool,
    include_thumbnails: bool,
    root_is_date_folder: bool,
) -> Optional[str]:
    rel_parts = _relative_parts(path, root)
    if _is_hidden_path(path, root):
        return "hidden"
    if not include_thumbnails and _is_thumbnail_path(path, root):
        return "thumbnail_dir"
    if exclude_failed:
        if root.name == "failed" or "failed" in rel_parts:
            return "failed"
    if not include_quarantine:
        if root.name == "quarantine" or "quarantine" in rel_parts:
            return "quarantine"
    if date_folder_only and not root_is_date_folder:
        # Support both legacy: <YYYY-MM-DD>/... and new: <content_subdir>/<YYYY-MM-DD>/...
        if not rel_parts:
            return "non_date_folder"
        first = rel_parts[0]
        if DATE_FOLDER_PATTERN.fullmatch(first):
            return None
        content_subdir = (getattr(settings, 'DEST_CONTENT_SUBDIR', '') or '').strip().strip('/\\')
        if content_subdir and first == content_subdir and len(rel_parts) >= 2 and DATE_FOLDER_PATTERN.fullmatch(rel_parts[1]):
            return None
        return "non_date_folder"
    return None


def collect_png_candidates(
    root: Path,
    *,
    date_folder_only: bool,
    exclude_failed: bool,
    include_quarantine: bool,
    include_thumbnails: bool,
    files: Optional[List[Path]] = None,
) -> Tuple[List[Path], Dict[str, int]]:
    excluded = {key: 0 for key in EXCLUDE_REASON_LABELS}
    candidates: List[Path] = []
    root_is_date_folder = DATE_FOLDER_PATTERN.fullmatch(root.name) is not None
    file_iter = files if files is not None else root.rglob("*")
    for png in file_iter:
        if not png.is_file():
            continue
        if png.suffix.lower() != ".png":
            excluded["non_png"] += 1
            continue
        reason = _exclude_reason(
            png,
            root,
            date_folder_only=date_folder_only,
            exclude_failed=exclude_failed,
            include_quarantine=include_quarantine,
            include_thumbnails=include_thumbnails,
            root_is_date_folder=root_is_date_folder,
        )
        if reason:
            excluded[reason] = excluded.get(reason, 0) + 1
            continue
        candidates.append(png)
    return candidates, excluded


def count_video_candidates(
    root: Path,
    *,
    date_folder_only: bool,
    exclude_failed: bool,
    include_quarantine: bool,
    include_thumbnails: bool,
) -> int:
    count = 0
    root_is_date_folder = DATE_FOLDER_PATTERN.fullmatch(root.name) is not None
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in VIDEO_EXTS:
            continue
        reason = _exclude_reason(
            path,
            root,
            date_folder_only=date_folder_only,
            exclude_failed=exclude_failed,
            include_quarantine=include_quarantine,
            include_thumbnails=include_thumbnails,
            root_is_date_folder=root_is_date_folder,
        )
        if reason:
            continue
        count += 1
    return count


def build_summary_lines(root: Path, stats: dict) -> List[str]:
    lines = [
        "=== 무결성 요약 ===",
        f"- 루트: {root}",
        f"- 스캔 파일(시도): {stats.get('scanned')}",
        f"- 성공(ok): {stats.get('ok')}",
        f"- 메타 없음: {stats.get('no_meta')}",
        f"- 노드 없음: {stats.get('no_nodes')}",
        f"- KSampler 없음: {stats.get('no_ksampler')}",
        f"- 파싱 에러: {stats.get('errors')}",
        f"- 긍정 프롬프트 누락: {stats.get('missing_positive')}",
        f"- 부정 프롬프트 누락: {stats.get('missing_negative')}",
    ]
    policy_parts = []
    if "include_videos" in stats:
        policy_parts.append(f"include_videos={bool(stats.get('include_videos'))}")
    if "date_folder_only" in stats:
        policy_parts.append(f"date-folder-only={bool(stats.get('date_folder_only'))}")
    if "exclude_failed" in stats:
        policy_parts.append(f"exclude_failed={bool(stats.get('exclude_failed'))}")
    if "include_thumbnails" in stats:
        policy_parts.append(f"include_thumbnails={bool(stats.get('include_thumbnails'))}")
    if "include_quarantine" in stats:
        policy_parts.append(f"include_quarantine={bool(stats.get('include_quarantine'))}")
    if policy_parts:
        lines.append(f"- 집계 옵션: {', '.join(policy_parts)}")
    excluded_counts = stats.get("excluded_counts") or {}
    if not excluded_counts:
        excluded_counts = {}
        for key in EXCLUDE_REASON_LABELS:
            legacy_key = f"excluded_{key}"
            if legacy_key in stats:
                excluded_counts[key] = stats.get(legacy_key, 0)
    excluded_total = sum(int(val or 0) for val in excluded_counts.values())
    lines.append(f"- 제외 합계: {excluded_total}")
    if excluded_total:
        reason_parts = [
            f"{EXCLUDE_REASON_LABELS.get(key, key)} {count}건"
            for key, count in excluded_counts.items()
            if count
        ]
        lines.append(f"- 제외 사유: {', '.join(reason_parts)}")
    else:
        lines.append("- 제외 사유: 없음")
    candidate_total = stats.get("candidate_total")
    scanned = stats.get("scanned")
    if candidate_total is not None and scanned is not None:
        diff = int(candidate_total) - int(scanned)
        lines.append(f"- 후보 → 실제 스캔: {candidate_total} → {scanned} (차이 {diff})")
        gap_counts = stats.get("scan_gap_counts") or {}
        gap_total = sum(int(val or 0) for val in gap_counts.values())
        stop_reason = stats.get("scan_stop_reason")
        if stop_reason:
            stop_label = SCAN_STOP_REASON_LABELS.get(stop_reason, stop_reason)
            lines.append(f"- 스캔 중단 원인: {stop_label}")
        else:
            lines.append("- 스캔 중단 원인: 없음")
        if diff <= 0:
            lines.append("- 차이 사유: 없음")
        elif gap_total:
            gap_parts = [
                f"{SCAN_GAP_REASON_LABELS.get(key, key)} {count}건"
                for key, count in gap_counts.items()
                if count
            ]
            lines.append(f"- 차이 사유: {', '.join(gap_parts)}")
        else:
            lines.append("- 차이 사유: 집계 정보 없음")
        limit_skipped = int(gap_counts.get("limit_reached", 0) or 0)
        if limit_skipped:
            lines.append(f"- ⚠️ 한도 초과로 생략된 파일 수: {limit_skipped}건")
    diagnostics_skipped = int(stats.get("diagnostics_skipped", 0) or 0)
    if diagnostics_skipped:
        lines.append(f"- 진단 샘플 제한: 상한 도달로 {diagnostics_skipped}건 미기록")
    else:
        lines.append("- 진단 샘플 제한: 미도달")
    if stats.get("candidate_total") is not None:
        if stats.get("include_videos"):
            lines.append(
                "- 비교 집계: PNG {png} + 영상 {videos} = {total}".format(
                    png=stats.get("candidate_total", 0),
                    videos=stats.get("video_candidates", 0),
                    total=stats.get("aggregate_total", 0),
                )
            )
        else:
            lines.append(f"- 비교 집계: PNG {stats.get('candidate_total', 0)}")
    return lines


def print_summary(root: Path, stats: dict, *, log_cb=None):
    _emit("", log_cb)
    for line in build_summary_lines(root, stats):
        _emit(line, log_cb)


def _record_scan_gap(stats: dict, reason: str, total: Optional[int]) -> None:
    if total is None:
        return
    remaining = max(int(total) - int(stats.get("scanned", 0)), 0)
    gap_counts = stats.setdefault("scan_gap_counts", {})
    gap_counts[reason] = gap_counts.get(reason, 0) + remaining


def build_missing_sample_entry(result: dict, miss_pos: bool, miss_neg: bool) -> dict:
    return {
        "file": result.get("file"),
        "missing_positive": miss_pos,
        "missing_negative": miss_neg,
        "sampler": result.get("sampler"),
        "scheduler": result.get("scheduler"),
    }


def build_missing_diagnostic(result: dict, status: str, png: Path) -> dict:
    diag = {
        "file": str(png),
        "status": status,
        "positive": {"missing": None},
        "negative": {"missing": None},
        "sampler": None,
        "scheduler": None,
        "seed": None,
        "steps": None,
    }
    if status != "ok":
        return diag
    diag["positive"]["missing"] = result.get("positive_prompt") is None
    diag["negative"]["missing"] = result.get("negative_prompt") is None
    diag["sampler"] = result.get("sampler")
    diag["scheduler"] = result.get("scheduler")
    diag["seed"] = result.get("seed")
    diag["steps"] = result.get("steps")
    return diag


def scan(
    root: Path,
    limit: int = 0,
    *,
    include_results: bool = False,
    include_missing_samples: bool = False,
    missing_samples_limit: int = settings.INTEGRITY_MISSING_SAMPLES_LIMIT,
    include_diagnostics: bool = False,
    diagnostics_limit: int = settings.INTEGRITY_DIAGNOSTICS_LIMIT,
    progress_cb=None,
    cancel_event=None,
    files: Optional[List[Path]] = None,
    date_folder_only: bool = False,
    exclude_failed: bool = False,
    include_quarantine: bool = False,
    include_thumbnails: bool = True,
):
    stats = {
        "scanned": 0, "ok": 0, "no_meta": 0, "no_nodes": 0, "no_ksampler": 0,
        "errors": 0, "missing_positive": 0, "missing_negative": 0, "read_failed": 0,
        "diagnostics_skipped": 0,
    }
    results: List[dict] = []
    missing_samples: List[dict] = []
    diagnostics: List[dict] = []
    sample_lists = {
        "no_meta": [],
        "no_ksampler": [],
        "missing_positive": [],
        "read_failed": [],
    }
    sample_limit_reached: set[str] = set()

    def record_sample(category: str, value: str) -> None:
        if missing_samples_limit <= 0 or len(sample_lists[category]) < missing_samples_limit:
            sample_lists[category].append(value)
        elif missing_samples_limit > 0:
            sample_limit_reached.add(category)

    count = 0
    candidates, excluded_counts = collect_png_candidates(
        root,
        date_folder_only=date_folder_only,
        exclude_failed=exclude_failed,
        include_quarantine=include_quarantine,
        include_thumbnails=include_thumbnails,
        files=files,
    )
    total = len(candidates) if candidates is not None else None
    stats["candidate_total"] = total
    stats["excluded_counts"] = excluded_counts
    stats["scan_gap_counts"] = {key: 0 for key in SCAN_GAP_REASON_LABELS}
    for png in candidates:
        if cancel_event is not None and cancel_event.is_set():
            stats["cancelled"] = True
            stats["scan_stop_reason"] = "cancelled"
            _record_scan_gap(stats, "cancelled", total)
            break
        stats["scanned"] += 1
        try:
            result, status = parse_png(png)
            if status == "ok":
                stats["ok"] += 1
                if include_results:
                    results.append(result)
                miss_pos = result.get("positive_prompt") is None
                miss_neg = result.get("negative_prompt") is None
                if miss_pos:
                    stats["missing_positive"] += 1
                    record_sample("missing_positive", result.get("file") or str(png))
                if REQUIRE_NEGATIVE_PROMPT and miss_neg:
                    stats["missing_negative"] += 1
                missing_any = miss_pos or miss_neg
                if include_missing_samples and missing_any:
                    if missing_samples_limit <= 0 or len(missing_samples) < missing_samples_limit:
                        missing_samples.append(build_missing_sample_entry(result, miss_pos, miss_neg))
                if include_diagnostics and missing_any:
                    if diagnostics_limit <= 0 or len(diagnostics) < diagnostics_limit:
                        diagnostics.append(build_missing_diagnostic(result, status, png))
                    else:
                        stats["diagnostics_skipped"] += 1
                        stats["diagnostics_limit_reached"] = True
            elif status == "read_failed":
                stats["read_failed"] += 1
                excluded_counts["read_failed"] = excluded_counts.get("read_failed", 0) + 1
                record_sample("read_failed", str(png))
            else:
                stats[status] = stats.get(status, 0) + 1
                if status == "no_meta":
                    record_sample("no_meta", str(png))
                elif status == "no_ksampler":
                    record_sample("no_ksampler", str(png))
        except Exception:
            stats["errors"] += 1
        count += 1
        if progress_cb and total:
            progress = (count / total) * 100 if total else 0
            progress_cb(progress, f"진행 {count}/{total}", None)
        if limit and stats["ok"] >= limit and include_results:
            stats["scan_stop_reason"] = "limit_reached"
            _record_scan_gap(stats, "limit_reached", total)
            break

    payload = {"stats": stats}
    if include_results:
        payload["results"] = results
    if include_missing_samples:
        payload["missing_samples"] = missing_samples
    if include_diagnostics:
        payload["diagnostics"] = diagnostics
    payload["sample_report"] = {
        "limit": missing_samples_limit,
        "limit_applied": missing_samples_limit > 0 and bool(sample_limit_reached),
        "limit_applied_categories": sorted(sample_limit_reached),
        "samples": sample_lists,
    }
    return payload


def write_jsonl(records: List[dict], path: Path) -> None:
    ensure_parent(path)
    with path.open("w", encoding="utf-8") as writer:
        for record in records:
            writer.write(json.dumps(record, ensure_ascii=False) + "\n")


def write_json(path: Path, payload: dict) -> None:
    ensure_parent(path)
    with path.open("w", encoding="utf-8") as writer:
        json.dump(payload, writer, ensure_ascii=False, indent=2)


def run_integrity_scan(
    root: Path | str,
    dry_run: bool = True,
    limit: int = 0,
    summary_only: bool = True,
    missing_samples_limit: int = settings.INTEGRITY_MISSING_SAMPLES_LIMIT,
    diagnostics_limit: int = settings.INTEGRITY_DIAGNOSTICS_LIMIT,
    include_videos: bool = False,
    date_folder_only: bool = False,
    exclude_failed: bool = False,
    include_quarantine: bool = False,
    include_thumbnails: bool = False,
    *,
    log_cb=None,
    progress_cb=None,
    cancel_event=None,
) -> dict:
    root_path = Path(root)
    if not root_path.exists():
        raise FileNotFoundError(f"루트 경로가 존재하지 않습니다: {root_path}")

    mode_label = "드라이런" if dry_run else "실행"
    _emit(f"PNG 무결성 검사 시작 ({mode_label})", log_cb)
    _emit(f"실제 스캔 루트: {root_path}", log_cb)
    limit_label = "제한 없음" if limit <= 0 else f"{limit}건"
    _emit(f"최대 검사 수: {limit_label}", log_cb)
    samples_label = "제한 없음" if missing_samples_limit <= 0 else f"{missing_samples_limit}건"
    diagnostics_label = "제한 없음" if diagnostics_limit <= 0 else f"{diagnostics_limit}건"
    _emit(f"진단 한도(샘플 제한): {samples_label}", log_cb)
    _emit(f"진단 한도(내부 상한): {diagnostics_label}", log_cb)
    filter_parts = [
        f"날짜 폴더만={'예' if date_folder_only else '아니오'}",
        f"failed 제외={'예' if exclude_failed else '아니오'}",
        f"격리 폴더 포함={'예' if include_quarantine else '아니오'}",
        f"영상 포함={'예' if include_videos else '아니오'}",
        f"썸네일 포함={'예' if include_thumbnails else '아니오'}",
    ]
    _emit(f"필터 조건: {', '.join(filter_parts)}", log_cb)
    files = None
    video_candidates = (
        count_video_candidates(
            root_path,
            date_folder_only=date_folder_only,
            exclude_failed=exclude_failed,
            include_quarantine=include_quarantine,
            include_thumbnails=include_thumbnails,
        )
        if include_videos
        else 0
    )
    scan_payload = scan(
        root_path,
        limit=limit,
        include_results=not summary_only,
        include_missing_samples=True,
        missing_samples_limit=missing_samples_limit,
        include_diagnostics=True,
        diagnostics_limit=diagnostics_limit,
        progress_cb=progress_cb,
        cancel_event=cancel_event,
        files=files,
        date_folder_only=date_folder_only,
        exclude_failed=exclude_failed,
        include_quarantine=include_quarantine,
        include_thumbnails=include_thumbnails,
    )
    stats = scan_payload.get("stats", {})
    stats["include_videos"] = include_videos
    stats["date_folder_only"] = date_folder_only
    stats["exclude_failed"] = exclude_failed
    stats["include_quarantine"] = include_quarantine
    stats["include_thumbnails"] = include_thumbnails
    excluded_counts = stats.get("excluded_counts", {})
    for key, count in excluded_counts.items():
        stats[f"excluded_{key}"] = count
    if include_videos:
        stats["video_candidates"] = video_candidates
        stats["aggregate_total"] = (stats.get("candidate_total") or 0) + video_candidates
    if stats.get("candidate_total") is not None:
        _emit(f"대상 PNG: {stats.get('candidate_total')}건", log_cb)
    print_summary(root_path, stats, log_cb=log_cb)

    status = "ok" if stats.get("errors", 0) == 0 else "failed"
    if stats.get("cancelled"):
        status = "cancelled"
    sample_report = scan_payload.get("sample_report", {})
    report_name = f"integrity_samples_{now_str()}.json"
    report_dir = Path(settings.DATA_DIR) / "integrity_reports"
    report_path = report_dir / report_name
    sample_report.setdefault("report", {})
    sample_report["report"].update({
        "file": report_name,
        "path": str(report_path),
        "download_url": f"/data/integrity-report/{report_name}",
    })
    report_payload = {
        "generated_at": datetime.now().isoformat(),
        "root": str(root_path),
        "mode": "dry" if dry_run else "execute",
        "summary": stats,
        "sample_report": sample_report,
    }
    try:
        write_json(report_path, report_payload)
        if sample_report.get("limit_applied"):
            _emit("샘플 제한 적용됨", log_cb)
        _emit(f"샘플 리포트 저장: {report_path}", log_cb)
    except Exception:
        _emit("샘플 리포트 저장 실패", log_cb)
    stats["sample_report"] = sample_report
    return {
        "status": status,
        "message": "PNG 무결성 검사 완료",
        "summary": stats,
        "missing_samples": scan_payload.get("missing_samples", []),
        "diagnostics": scan_payload.get("diagnostics", []),
    }

def inspect_missing_samples(
    root: Path,
    samples: int = 20,
    search_limit: int = 2000,
    *,
    progress_cb=None,
) -> dict:
    files = sorted(root.rglob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    total = min(search_limit, len(files))
    shown = 0
    start = time.time()
    missing_samples: List[dict] = []
    scanned = 0
    for idx, png in enumerate(files[:total], 1):
        scanned = idx
        result, status = parse_png(png)
        if status == "ok":
            miss_pos = result.get("positive_prompt") is None
            miss_neg = result.get("negative_prompt") is None
            if miss_pos or miss_neg:
                missing_samples.append(build_missing_sample_entry(result, miss_pos, miss_neg))
                shown += 1
                if shown >= samples:
                    break
        if progress_cb and idx % 200 == 0:
            elapsed = time.time() - start
            progress_cb(idx / total * 100, f"[진행] {idx}/{total} 검사, 발견 {shown}건, 경과 {elapsed:.1f}s", None)
    return {
        "scanned": scanned,
        "total": total,
        "found": shown,
        "missing_samples": missing_samples,
    }

# (옵션) 누락 진단 로직 (간단 버전)
def diagnose_missing_case(png: Path):
    result, status = parse_png(png)
    diag = build_missing_diagnostic(result, status, png)
    return result, diag

# ========= 메뉴 =========
def main():
    root = read_env_root()
    print("ComfyUI PNG 메타데이터 검사 도구")
    print(f"- 기본 루트(settings.DEST): {root}\n")

    while True:
        print("===== 메뉴 =====")
        print("[1] 빠른 드라이런 (기본 50개, 콘솔 출력)")
        print("[2] 전체 드라이런 (전부, 콘솔 출력)")
        print("[3] 전체 스캔 → JSONL 저장")
        print("[4] 무결성 요약만 보기 (콘솔)")
        print("[5] 루트 경로 변경")
        print("[6] 종료")
        print("[7] 누락 샘플 미리보기 (최대 20개)")
        print("[8] 누락 진단 JSONL 저장")
        sel = input("선택: ").strip()

        if sel == "1":
            n = ask_int("최대 출력 개수?", 50)
            payload = scan(root, limit=n, include_results=True)
            for result in payload.get("results", []):
                print_one(result)
            print_summary(root, payload.get("stats", {}))

        elif sel == "2":
            payload = scan(root, limit=0, include_results=True)
            for result in payload.get("results", []):
                print_one(result)
            print_summary(root, payload.get("stats", {}))

        elif sel == "3":
            default_out = Path("tests") / f"png_scan_{now_str()}.jsonl"
            dest = input(f"저장 경로 입력(기본 {default_out}): ").strip()
            path = Path(dest) if dest else default_out
            payload = scan(root, limit=0, include_results=True)
            write_jsonl(payload.get("results", []), path)
            print_summary(root, payload.get("stats", {}))
            print(f"저장 완료: {path}")

        elif sel == "4":
            maxn = ask_int("최대 파일 수? (0=무제한)", 0)
            files = None
            if maxn > 0:
                files = list(root.rglob("*.png"))[:maxn]
            payload = scan(root, limit=0, files=files)
            print_summary(root, payload.get("stats", {}))

        elif sel == "5":
            newr = input("새 루트 경로 입력: ").strip()
            if newr:
                r = Path(newr)
                if r.exists():
                    root = r
                    print(f"✓ 루트 변경: {root}")
                else:
                    print("❌ 경로가 존재하지 않습니다.")

        elif sel == "6":
            print("종료합니다.")
            break

        elif sel == "7":
            n = ask_int("샘플 개수?", 20)
            limit = ask_int("최대 탐색 파일 수? (0=무제한)", 2000)
            if limit <= 0: limit = 10_000_000
            report = inspect_missing_samples(root, samples=n, search_limit=limit)
            missing_samples = report.get("missing_samples", [])
            for sample in missing_samples:
                print(f"- {sample.get('file')}")
                print(
                    "  · pos 누락: {missing_positive}, neg 누락: {missing_negative}, sampler: {sampler}, scheduler: {scheduler}".format(
                        **sample
                    )
                )
            if not missing_samples:
                print("누락 샘플이 없습니다(검색 범위 내).")

        elif sel == "8":
            default_out = Path("tests") / f"missing_diagnostics_{now_str()}.jsonl"
            dest = input(f"저장 경로 입력(기본 {default_out}): ").strip()
            save_path = Path(dest) if dest else default_out
            maxn = ask_int("최대 파일 수? (0=무제한)", 0)
            print("누락 케이스 진단을 시작합니다...")
            payload = scan(
                root,
                include_diagnostics=True,
                diagnostics_limit=maxn if maxn > 0 else 0,
            )
            diagnostics = payload.get("diagnostics", [])
            write_jsonl(diagnostics, save_path)
            print(f"완료: {len(diagnostics)}건 저장 → {save_path}")

        else:
            print("알 수 없는 선택입니다.\n")

if __name__ == "__main__":
    main()
