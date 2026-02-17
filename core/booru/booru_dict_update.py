from __future__ import annotations

import csv
import gzip
import io
import re
import json
import hashlib
import logging
import os
import shutil
import subprocess
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple
from urllib.parse import quote, urlparse

import requests

from settings import (
    BOORU_DICT_ALLOW_CUSTOM_URL,
    BOORU_DICT_CACHE_DIR,
    BOORU_DICT_CUSTOM_URL,
    BOORU_DICT_GIT_FILE,
    BOORU_DICT_GIT_REF,
    BOORU_DICT_GIT_URL,
    BOORU_DICT_LOCAL_FILE,
    BOORU_DICT_SKIP_IF_SAME_SHA256,
    BOORU_DICT_SOURCE_KIND,
    BOORU_DICT_SOURCE_PRESET,
    DB_PATH,
)
from core.booru.booru_dict import ensure_booru_tables, get_booru_meta, normalize_booru_tag

logger = logging.getLogger(__name__)

DEFAULT_PRESET = "hf:newtextdoc1111/danbooru-tag-csv@main:danbooru_tags.csv"
_CATEGORY_MAP = {0: "general", 1: "artist", 3: "copyright", 4: "character", 5: "meta"}
_CATEGORY_NAMES = {"general", "artist", "copyright", "character", "meta"}
_TAG_KEYS = ("tag", "name", "booru_tag")
_CATEGORY_KEYS = ("category", "type", "tag_type", "cat", "category_id", "category_num", "tag_category")
_COUNT_KEYS = ("post_count", "count", "posts", "postcount", "postCount", "uses", "usage")
_SNIFF_DELIMITERS = [",", "\t", ";", "|"]
_SOURCE_KINDS = {"hf", "url", "git", "local"}


class BooruUpdateCancelled(RuntimeError):
    pass


def _emit_progress(progress_cb, progress: float, message: str, summary: dict | None = None) -> None:
    if progress_cb:
        progress_cb(progress=progress, message=message, summary=summary)


def _emit_log(log_cb, message: str) -> None:
    if log_cb:
        log_cb(message)
    else:
        logger.info(message)


def _check_cancelled(cancel_event) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise BooruUpdateCancelled()


def _normalize_source_kind(raw: str | None) -> str:
    kind = (raw or "hf").strip().lower()
    return kind if kind in _SOURCE_KINDS else "hf"


def _run_git(args: list[str], *, cwd: str | os.PathLike | None = None) -> subprocess.CompletedProcess:
    result = subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        cmd = " ".join(args)
        raise RuntimeError(f"git failed: {cmd} ({detail})")
    return result


def _sync_git_repo(
    repo_url: str,
    ref: str,
    repo_dir: str | os.PathLike,
    *,
    log_cb=None,
    cancel_event=None,
) -> str:
    repo_path = Path(repo_dir)
    if repo_path.exists() and not (repo_path / ".git").exists():
        raise RuntimeError(f"tag repo path is not a git repo: {repo_path}")

    ref = (ref or "main").strip() or "main"
    if not repo_path.exists():
        _emit_log(log_cb, f"git clone: {repo_url} ({ref})")
        _run_git(["git", "clone", "--depth", "1", "-b", ref, repo_url, repo_path.as_posix()])
    else:
        _emit_log(log_cb, f"git fetch: {repo_path}")
        _run_git(["git", "-C", repo_path.as_posix(), "fetch", "--all", "--prune"])
        _run_git(["git", "-C", repo_path.as_posix(), "checkout", ref])
        try:
            _run_git(["git", "-C", repo_path.as_posix(), "reset", "--hard", f"origin/{ref}"])
        except RuntimeError:
            _run_git(["git", "-C", repo_path.as_posix(), "reset", "--hard", ref])

    _check_cancelled(cancel_event)
    commit = _run_git(["git", "-C", repo_path.as_posix(), "rev-parse", "HEAD"]).stdout.strip()
    return commit

def sha256_file(path: str | os.PathLike) -> str:
    sha = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def ensure_decompressed_csv(gz_path: str | os.PathLike, out_csv_path: str | os.PathLike, *, log_cb=None) -> str:
    gz_path = Path(gz_path)
    out_csv_path = Path(out_csv_path)
    if out_csv_path.exists() and out_csv_path.stat().st_mtime >= gz_path.stat().st_mtime:
        return out_csv_path.as_posix()
    _emit_log(log_cb, f"gzip decompress: {gz_path} -> {out_csv_path}")
    with gzip.open(gz_path, "rb") as src, open(out_csv_path, "wb") as dst:
        shutil.copyfileobj(src, dst, length=1024 * 1024)
    return out_csv_path.as_posix()


def download_to_temp(url: str, tmp_path: str | os.PathLike, progress_cb=None, log_cb=None, cancel_event=None) -> int:
    tmp_path = Path(tmp_path)
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    downloaded = 0
    last_progress = -1
    last_tick = time.monotonic()

    try:
        with requests.get(url, stream=True, timeout=(10, 60)) as response:
            response.raise_for_status()
            total_raw = response.headers.get("Content-Length") or ""
            total_size = int(total_raw) if total_raw.isdigit() else 0
            if not total_size:
                _emit_log(log_cb, "Content-Length 없음: 진행률 표시가 제한됩니다.")

            with open(tmp_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    _check_cancelled(cancel_event)
                    if not chunk:
                        continue
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size:
                        progress = min(100, int(downloaded * 100 / total_size))
                        if progress_cb and progress != last_progress:
                            progress_cb(progress, f"다운로드 {progress}%", None)
                            last_progress = progress
                    else:
                        now = time.monotonic()
                        if progress_cb and now - last_tick >= 1.0:
                            progress_cb(0, f"다운로드 {downloaded} bytes", None)
                            last_tick = now

        if not total_size:
            _emit_log(log_cb, f"다운로드 크기: {downloaded} bytes")
        return downloaded
    except Exception:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            logger.exception("임시 다운로드 파일 정리 실패: %s", tmp_path)
        raise


def _parse_preset(preset: str) -> Tuple[str, str, str]:
    raw = (preset or "").strip()
    if not raw.startswith("hf:"):
        raise ValueError(f"지원하지 않는 프리셋 형식: {preset}")
    rest = raw[3:]
    if ":" not in rest:
        raise ValueError(f"프리셋 파일 지정이 누락되었습니다: {preset}")
    repo_part, file_part = rest.split(":", 1)
    repo_part = repo_part.strip()
    file_part = file_part.strip()
    if not repo_part or not file_part:
        raise ValueError(f"프리셋 값이 올바르지 않습니다: {preset}")
    if "@" in repo_part:
        repo, rev = repo_part.split("@", 1)
    else:
        repo, rev = repo_part, "main"
    repo = repo.strip()
    rev = (rev or "main").strip()
    if not repo:
        raise ValueError(f"프리셋 repo 값이 없습니다: {preset}")
    return repo, rev, file_part


def _preset_to_url(preset: str) -> str:
    repo, rev, file_path = _parse_preset(preset)
    safe_file = quote(file_path, safe="/")
    return f"https://huggingface.co/datasets/{repo}/resolve/{rev}/{safe_file}"


def _resolve_source() -> Tuple[str, str]:
    preset = (BOORU_DICT_SOURCE_PRESET or DEFAULT_PRESET).strip()
    allow_custom = bool(BOORU_DICT_ALLOW_CUSTOM_URL)
    custom_url = (BOORU_DICT_CUSTOM_URL or "").strip()
    if allow_custom and custom_url:
        return "", custom_url
    return preset, _preset_to_url(preset)


def _hf_fallback_presets(preset: str) -> list[str]:
    candidates: list[str] = []
    base = (preset or "").strip()
    if not base:
        return candidates
    candidates.append(base)
    if "danbooru_tags_full.csv.gz" in base:
        candidates.append(base.replace("danbooru_tags_full.csv.gz", "danbooru_tags.csv"))
    return candidates


def _resolve_filename(preset: str, url: str) -> str:
    if preset:
        try:
            _, _, file_path = _parse_preset(preset)
            name = Path(file_path).name
            return name or "danbooru_tags.csv"
        except Exception:
            pass
    path = urlparse(url).path
    name = os.path.basename(path)
    return name or "danbooru_tags.csv"


def _normalize_category(raw: Any) -> str:
    if raw is None:
        return "general"
    text = str(raw).strip()
    if not text:
        return "general"
    try:
        code = int(text)
    except (TypeError, ValueError):
        code = None
    if code is not None and code in _CATEGORY_MAP:
        return _CATEGORY_MAP[code]
    lowered = text.lower()
    return lowered if lowered in _CATEGORY_NAMES else "general"


def _normalize_count(raw: Any) -> int:
    if raw is None:
        return 0
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return 0


def _detect_header(first_row: Iterable[Any]) -> bool:
    for cell in first_row:
        key = str(cell or "").strip().lower().lstrip("\ufeff")
        if key in _TAG_KEYS or key in _CATEGORY_KEYS or key in _COUNT_KEYS:
            return True
    return False


def _make_dialect(delimiter: str) -> csv.Dialect:
    dialect_type = type("BooruDialect", (csv.excel,), {})
    dialect_type.delimiter = delimiter
    return dialect_type()


_COMPACT_RE = re.compile(r'^\s*([^,\t;|]+)\s*[,\\t;|]\s*(\d+)\s*[,\\t;|]\s*(\d+)\b')


def _try_parse_compact(cell: Any):
    """Parse 'tag,category,count,...' 형태에서 앞의 3개만 안정적으로 뽑는다."""
    if not isinstance(cell, str):
        return None
    m = _COMPACT_RE.match(cell)
    if not m:
        return None
    return m.group(1), m.group(2), m.group(3)


def _looks_like_header_line(cell: Any) -> bool:
    if not isinstance(cell, str):
        return False
    text = cell.lstrip("\ufeff").strip().lower()
    if not text:
        return False
    # 대표 헤더: tag,category,count,alias
    return text.startswith("tag") and ("category" in text) and ("count" in text)


def _pick_best_delimiter(sample: str, candidates: Iterable[str]) -> str:
    """
    Sniffer 대신 '컬럼 수' 기반으로 delimiter를 고른다.
    - 평균 컬럼 수가 크고
    - 3컬럼 이상인 라인이 많이 나오는 delimiter를 우선
    """
    lines = [ln for ln in (sample or "").splitlines() if ln.strip()]
    lines = lines[:50]
    if not lines:
        return ","

    best = ","
    best_score = -1.0

    for d in candidates:
        dialect = _make_dialect(d)
        try:
            reader = csv.reader(lines, dialect)
            widths = [len(r) for r in reader if r]
        except Exception:
            continue
        if not widths:
            continue

        avg = sum(widths) / len(widths)
        multi = sum(1 for w in widths if w >= 3) / len(widths)
        score = avg + (multi * 10.0)

        if score > best_score:
            best_score = score
            best = d

    return best


def _detect_dialect_and_header(
    csv_path: str | os.PathLike,
    log_cb=None,
) -> Tuple[csv.Dialect, bool]:
    with open(csv_path, "rb") as fb:
        with io.TextIOWrapper(fb, encoding="utf-8", errors="replace", newline="") as f:
            sample = f.read(8192)
            best_delim = _pick_best_delimiter(sample, _SNIFF_DELIMITERS)
            dialect = _make_dialect(best_delim)

            f.seek(0)
            reader = csv.reader(f, dialect)
            try:
                first_row = next(reader)
            except StopIteration:
                _emit_log(log_cb, f"CSV dialect delimiter='{dialect.delimiter}' has_header=False first_row_len=0")
                return dialect, False

            has_header = _detect_header(first_row)

            # delimiter가 잘못 잡혀 1칸으로 들어온 경우: 헤더/패턴으로 복구
            if len(first_row) == 1:
                cell = str(first_row[0] or "")
                # 헤더 감지용 split 시도
                for d in _SNIFF_DELIMITERS:
                    if d in cell:
                        split_cells = cell.split(d)
                        if _detect_header(split_cells):
                            dialect = _make_dialect(d)
                            has_header = True
                            first_row = split_cells
                            break

            _emit_log(
                log_cb,
                f"CSV dialect delimiter='{dialect.delimiter}' has_header={has_header} first_row_len={len(first_row)}",
            )
            return dialect, has_header


def import_booru_csv(
    csv_path: str | os.PathLike,
    *,
    mode: str = "replace",
    progress_cb=None,
    log_cb=None,
    cancel_event=None,
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    if mode not in {"replace", "upsert"}:
        raise ValueError("mode must be replace or upsert")

    created_conn = conn is None
    if conn is None:
        conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    ensure_booru_tables(cur=cur, conn=conn)

    file_size = os.path.getsize(csv_path)
    _emit_log(log_cb, f"CSV 로딩 시작: {csv_path} ({file_size} bytes)")
    _emit_progress(progress_cb, 0, "CSV 읽는 중")
    _check_cancelled(cancel_event)

    tag_count = 0
    last_progress = -1
    last_tick = time.monotonic()
    batch: list[tuple[str, str, int]] = []
    batch_size = 2000

    insert_table = "booru_dict_new" if mode == "replace" else "booru_dict"
    if mode == "upsert":
        insert_sql = (
            "INSERT INTO booru_dict (tag, category, post_count, updated_at) "
            "VALUES (?, ?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(tag) DO UPDATE SET "
            "category=excluded.category, post_count=excluded.post_count, updated_at=CURRENT_TIMESTAMP"
        )
    else:
        insert_sql = f"INSERT INTO {insert_table} (tag, category, post_count) VALUES (?, ?, ?)"

    try:
        cur.execute("BEGIN")
        if mode == "replace":
            cur.execute("DROP TABLE IF EXISTS booru_dict_new")
            cur.execute(
                '''
                CREATE TABLE booru_dict_new (
                    tag TEXT PRIMARY KEY,
                    category TEXT DEFAULT 'general',
                    post_count INTEGER DEFAULT 0,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                '''
            )

        dialect, has_header = _detect_dialect_and_header(csv_path, log_cb=log_cb)
        _emit_log(log_cb, f"CSV 헤더 {'감지됨' if has_header else '없음'}")

        with open(csv_path, "rb") as fb:
            with io.TextIOWrapper(fb, encoding="utf-8", errors="replace", newline="") as f:
                reader = csv.reader(f, dialect)
                first_row = next(reader, [])
                if has_header:
                    fieldnames = [str(item or "").strip().lower().lstrip("\ufeff") for item in first_row]
                    dict_reader = csv.DictReader(f, fieldnames=fieldnames, dialect=dialect)
                    row_iter: Iterable[Any] = dict_reader
                else:
                    def row_iter_fn():
                        if first_row:
                            yield first_row
                        yield from reader

                    row_iter = row_iter_fn()

                for row in row_iter:
                    _check_cancelled(cancel_event)
                    tag_raw: Optional[str] = None
                    category_raw = None
                    count_raw = None
                    if isinstance(row, dict):
                        norm = {str(k).strip().lower(): v for k, v in row.items()}
                        for key in _TAG_KEYS:
                            tag_raw = norm.get(key) or tag_raw
                        for key in _CATEGORY_KEYS:
                            category_raw = norm.get(key) or category_raw
                        for key in _COUNT_KEYS:
                            count_raw = norm.get(key) or count_raw
                        # (보강) 헤더/단일컬럼 dict가 들어온 경우 복구
                        if (not tag_raw) and len(norm) == 1:
                            only_val = next(iter(norm.values()))
                            if _looks_like_header_line(only_val):
                                continue
                            parsed = _try_parse_compact(only_val)
                            if parsed:
                                tag_raw, category_raw, count_raw = parsed
                            else:
                                # 복구 불가능하면 이 row는 버린다(가짜 tag 저장 방지)
                                continue
                    else:
                        if not row:
                            continue

                        # 원본 첫 셀로 헤더 판단(헤더를 tag로 저장하는 사고 방지)
                        first_cell = row[0]
                        if _looks_like_header_line(first_cell):
                            continue

                        tag_raw = row[0]
                        category_raw = row[1] if len(row) > 1 else None
                        count_raw = row[2] if len(row) > 2 else None

                        # delimiter 오탐으로 row가 1칸짜리인 경우가 많음 → compact 파싱으로 강제 복구
                        if isinstance(first_cell, str) and (len(row) == 1 or category_raw is None or count_raw is None):
                            parsed = _try_parse_compact(first_cell)
                            if parsed:
                                tag_raw, category_raw, count_raw = parsed
                            else:
                                # 정규식이 못 잡으면 split fallback(앞 3개만 사용)
                                if len(row) == 1:
                                    cell = first_cell
                                    for d in _SNIFF_DELIMITERS:
                                        if d in cell:
                                            parts = [p.strip() for p in cell.split(d)]
                                            if len(parts) >= 3 and parts[0]:
                                                tag_raw, category_raw, count_raw = parts[0], parts[1], parts[2]
                                                break

                    if not tag_raw:
                        continue
                    tag_norm = normalize_booru_tag(tag_raw)
                    if not tag_norm:
                        continue
                    category = _normalize_category(category_raw)
                    post_count = _normalize_count(count_raw)
                    batch.append((tag_norm, category, post_count))
                    if len(batch) >= batch_size:
                        cur.executemany(insert_sql, batch)
                        tag_count += len(batch)
                        batch.clear()

                    if progress_cb and file_size:
                        now = time.monotonic()
                        if now - last_tick >= 0.5:
                            progress = None
                            try:
                                pos = fb.tell()
                                progress = min(99, int(pos * 100 / file_size))
                            except Exception:
                                progress = None
                            if progress is not None and progress != last_progress:
                                progress_cb(progress, f"CSV 처리 중 ({tag_count}건)", None)
                                last_progress = progress
                            last_tick = now

        if batch:
            cur.executemany(insert_sql, batch)
            tag_count += len(batch)
            batch.clear()

        if mode == "replace":
            cur.execute("DROP TABLE IF EXISTS booru_dict")
            cur.execute("ALTER TABLE booru_dict_new RENAME TO booru_dict")
            cur.execute(
                '''
                CREATE INDEX IF NOT EXISTS idx_booru_dict_category_count
                ON booru_dict(category, post_count DESC)
                '''
            )
        else:
            cur.execute(
                '''
                CREATE INDEX IF NOT EXISTS idx_booru_dict_category_count
                ON booru_dict(category, post_count DESC)
                '''
            )

        conn.commit()
        _emit_log(log_cb, f"CSV import 완료: {tag_count} tags")
        _emit_progress(progress_cb, 100, f"CSV import 완료 ({tag_count}건)")
        return tag_count
    except BooruUpdateCancelled:
        conn.rollback()
        _emit_log(log_cb, "CSV import 취소됨")
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        if created_conn:
            conn.close()


def _load_booru_meta(conn: sqlite3.Connection) -> Dict[str, Any]:
    meta = get_booru_meta(conn=conn)
    if "tag_count" in meta:
        try:
            meta["tag_count"] = int(meta["tag_count"])
        except (TypeError, ValueError):
            pass
    return meta


def _save_booru_meta(conn: sqlite3.Connection, values: Dict[str, Any]) -> None:
    cur = conn.cursor()
    payload = [(str(k), "" if v is None else str(v)) for k, v in values.items()]
    cur.executemany("REPLACE INTO booru_meta(key, value) VALUES (?, ?)", payload)
    conn.commit()


def _summarize_category_counts(conn: sqlite3.Connection) -> Dict[str, int]:
    cur = conn.cursor()
    cur.execute("SELECT category, COUNT(*) FROM booru_dict GROUP BY category")
    rows = cur.fetchall()
    result: Dict[str, int] = {}
    for category, count in rows:
        if category is None:
            continue
        try:
            result[str(category)] = int(count)
        except (TypeError, ValueError):
            continue
    return result


def _build_summary(meta: Dict[str, Any], *, source_preset: str, source_url: str, skipped: bool = False) -> Dict[str, Any]:
    tag_count = meta.get("tag_count")
    sha256 = meta.get("last_sha256")
    imported_at = meta.get("imported_at")
    sample_items = []
    if imported_at:
        sample_items.append(f"imported_at: {imported_at}")
    if tag_count is not None:
        sample_items.append(f"tag_count: {tag_count}")
    if sha256:
        sample_items.append(f"sha256: {sha256}")
    if source_preset:
        sample_items.append(f"source_preset: {source_preset}")
    if source_url:
        sample_items.append(f"source_url: {source_url}")
    git_commit = meta.get("source_git_commit")
    if git_commit:
        sample_items.append(f"source_git_commit: {git_commit}")
    if skipped:
        sample_items.append("skipped: sha256 동일")

    return {
        "sample_label": "Danbooru 태그DB",
        "sample_items": sample_items,
        "tag_count": tag_count,
        "sha256": sha256,
        "imported_at": imported_at,
        "source_preset": source_preset,
        "source_url": source_url,
        "skipped": skipped,
    }


def run_booru_dict_update(
    *,
    progress_cb=None,
    log_cb=None,
    cancel_event=None,
    force: bool = False,
) -> Dict[str, Any]:
    try:
        ensure_booru_tables()

        _emit_progress(progress_cb, 2, "태그DB 업데이트 준비 중")
        _check_cancelled(cancel_event)

        source_kind = _normalize_source_kind(BOORU_DICT_SOURCE_KIND)
        source_preset = ""
        source_url = ""
        source_git_commit = ""

        cache_dir = Path(BOORU_DICT_CACHE_DIR or "data/booru_cache")
        cache_dir.mkdir(parents=True, exist_ok=True)

        _emit_log(log_cb, f"resolved source_kind: {source_kind}")

        if source_kind == "hf":
            source_preset, source_url = _resolve_source()
            if not source_url:
                return {"status": "error", "error": "source_url missing", "message": "booru dict update failed"}

            hf_candidates: list[tuple[str, str]] = []
            for candidate_preset in _hf_fallback_presets(source_preset):
                try:
                    candidate_url = _preset_to_url(candidate_preset)
                except Exception:
                    continue
                if not candidate_url:
                    continue
                hf_candidates.append((candidate_preset, candidate_url))
            if not hf_candidates:
                hf_candidates.append((source_preset, source_url))

            last_http_error: Exception | None = None
            downloaded = False
            for idx, (candidate_preset, candidate_url) in enumerate(hf_candidates):
                source_preset = candidate_preset
                source_url = candidate_url
                filename = _resolve_filename(source_preset, source_url)
                final_path = cache_dir / filename
                tmp_path = cache_dir / f"{filename}.part"

                def download_progress(progress: float, message: str | None = None, summary=None) -> None:
                    mapped = 2 + (progress * 0.33)
                    _emit_progress(progress_cb, mapped, message or "download", summary)

                _emit_log(log_cb, f"download start: {source_url}")
                try:
                    download_to_temp(
                        source_url,
                        tmp_path,
                        progress_cb=download_progress,
                        log_cb=log_cb,
                        cancel_event=cancel_event,
                    )
                except requests.HTTPError as exc:
                    status_code = exc.response.status_code if exc.response is not None else None
                    last_http_error = exc
                    if status_code == 404 and idx < len(hf_candidates) - 1:
                        _emit_log(log_cb, f"source not found (404), fallback source 시도: {source_url}")
                        continue
                    raise

                if cancel_event is not None and cancel_event.is_set():
                    try:
                        if Path(tmp_path).exists():
                            Path(tmp_path).unlink()
                    except Exception:
                        logger.exception("download cancelled; cleanup failed: %s", tmp_path)
                    raise BooruUpdateCancelled()
                try:
                    os.replace(tmp_path, final_path)
                except Exception:
                    try:
                        if Path(tmp_path).exists():
                            Path(tmp_path).unlink()
                    except Exception:
                        logger.exception("download cleanup failed: %s", tmp_path)
                    raise
                _emit_log(log_cb, f"download done: {final_path}")
                downloaded = True
                break

            if not downloaded and last_http_error:
                raise last_http_error
        elif source_kind == "url":
            source_url = (BOORU_DICT_CUSTOM_URL or "").strip()
            if not source_url:
                return {"status": "error", "error": "custom_url missing", "message": "booru dict update failed"}
            filename = _resolve_filename("", source_url)
            final_path = cache_dir / filename
            tmp_path = cache_dir / f"{filename}.part"

            def download_progress(progress: float, message: str | None = None, summary=None) -> None:
                mapped = 2 + (progress * 0.33)
                _emit_progress(progress_cb, mapped, message or "download", summary)

            _emit_log(log_cb, f"download start: {source_url}")
            download_to_temp(
                source_url,
                tmp_path,
                progress_cb=download_progress,
                log_cb=log_cb,
                cancel_event=cancel_event,
            )
            if cancel_event is not None and cancel_event.is_set():
                try:
                    if Path(tmp_path).exists():
                        Path(tmp_path).unlink()
                except Exception:
                    logger.exception("download cancelled; cleanup failed: %s", tmp_path)
                raise BooruUpdateCancelled()
            try:
                os.replace(tmp_path, final_path)
            except Exception:
                try:
                    if Path(tmp_path).exists():
                        Path(tmp_path).unlink()
                except Exception:
                    logger.exception("download cleanup failed: %s", tmp_path)
                raise
            _emit_log(log_cb, f"download done: {final_path}")
        elif source_kind == "git":
            repo_url = (BOORU_DICT_GIT_URL or "").strip()
            if not repo_url:
                return {"status": "error", "error": "git_url missing", "message": "booru dict update failed"}
            git_ref = (BOORU_DICT_GIT_REF or "main").strip() or "main"
            git_file = (BOORU_DICT_GIT_FILE or "danbooru_tags.csv").strip() or "danbooru_tags.csv"
            repo_dir = cache_dir / "tagrepo"
            _emit_progress(progress_cb, 10, "git sync")
            source_git_commit = _sync_git_repo(
                repo_url,
                git_ref,
                repo_dir,
                log_cb=log_cb,
                cancel_event=cancel_event,
            )
            final_path = repo_dir / git_file
            if not final_path.is_file():
                return {
                    "status": "error",
                    "error": f"git_file not found: {final_path}",
                    "message": "booru dict update failed",
                }
            source_url = repo_url
            source_preset = f"git:{repo_url}@{git_ref}:{git_file}"
        elif source_kind == "local":
            local_path = (BOORU_DICT_LOCAL_FILE or "").strip()
            if not local_path:
                return {"status": "error", "error": "local_file missing", "message": "booru dict update failed"}
            final_path = Path(local_path)
            if not final_path.is_file():
                return {
                    "status": "error",
                    "error": f"local_file not found: {final_path}",
                    "message": "booru dict update failed",
                }
            source_url = final_path.as_posix()
            source_preset = "local"
        else:
            return {
                "status": "error",
                "error": f"unknown source_kind: {source_kind}",
                "message": "booru dict update failed",
            }

        _emit_log(log_cb, f"resolved source_path: {final_path}")

        import_path = final_path
        if final_path.suffix.lower() == ".gz":
            csv_path = final_path.with_suffix("")
            import_path = Path(ensure_decompressed_csv(final_path, csv_path, log_cb=log_cb))
        _emit_log(log_cb, f"resolved import_path: {import_path}")
        try:
            file_size = os.path.getsize(import_path)
            _emit_log(log_cb, f"import file_size: {file_size} bytes")
        except Exception:
            _emit_log(log_cb, "import file_size: unknown")

        _emit_progress(progress_cb, 38, "sha256 계산 중")
        sha256 = sha256_file(final_path)
        _emit_log(log_cb, f"sha256: {sha256}")

        conn = sqlite3.connect(DB_PATH)
        try:
            ensure_booru_tables(conn=conn, cur=conn.cursor())
            meta = _load_booru_meta(conn)
            last_sha = meta.get("last_sha256")
            if force and BOORU_DICT_SKIP_IF_SAME_SHA256 and last_sha and last_sha == sha256:
                _emit_log(log_cb, "force=1: sha256 동일해도 import를 강제로 수행합니다.")
            if not force and BOORU_DICT_SKIP_IF_SAME_SHA256 and last_sha and last_sha == sha256:
                message = "변경 없음(sha256 동일) → import 생략"
                summary = _build_summary(meta, source_preset=source_preset, source_url=source_url, skipped=True)
                _emit_log(log_cb, message)
                _emit_progress(progress_cb, 100, message, summary=summary)
                return {"status": "ok", "message": message, "summary": summary}

            def import_progress(progress: float, message: str | None = None, summary=None) -> None:
                mapped = 45 + (progress * 0.5)
                _emit_progress(progress_cb, mapped, message or "CSV import 중", summary)

            _emit_log(log_cb, "CSV import 시작")
            tag_count = import_booru_csv(
                import_path,
                mode="replace",
                progress_cb=import_progress,
                log_cb=log_cb,
                cancel_event=cancel_event,
                conn=conn,
            )
            _check_cancelled(cancel_event)

            imported_at = datetime.now().isoformat(timespec="seconds")
            category_counts = _summarize_category_counts(conn)
            category_counts_json = json.dumps(category_counts)
            _save_booru_meta(
                conn,
                {
                    "imported_at": imported_at,
                    "source_preset": source_preset,
                    "source_url": source_url,
                    "source_import_path": import_path.as_posix(),
                    "source_git_commit": source_git_commit,
                    "last_sha256": sha256,
                    "tag_count": tag_count,
                    "category_counts_json": category_counts_json,
                },
            )
            meta = _load_booru_meta(conn)
        finally:
            conn.close()

        summary = _build_summary(meta, source_preset=source_preset, source_url=source_url, skipped=False)
        _emit_progress(progress_cb, 100, "Danbooru 태그DB 업데이트 완료", summary=summary)
        return {"status": "ok", "message": "Danbooru 태그DB 업데이트 완료", "summary": summary}
    except BooruUpdateCancelled:
        _emit_log(log_cb, "태그DB 업데이트 취소됨")
        return {"status": "cancelled", "message": "태그DB 업데이트 취소"}
    except Exception as exc:
        _emit_log(log_cb, f"태그DB 업데이트 실패: {exc}")
        _emit_progress(progress_cb, 100, f"태그DB 업데이트 실패: {exc}", summary={"error": str(exc)})
        return {"status": "error", "error": str(exc), "message": "Danbooru 태그DB 업데이트 실패"}
