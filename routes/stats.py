from __future__ import annotations

from typing import Optional

from flask import Blueprint, jsonify, render_template, request

from core.db.search_utils import ensure_image_tables, get_lora_usage_counts, get_model_usage_counts

bp = Blueprint("stats", __name__)


def _parse_recent_days(value: Optional[str]) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        days = int(value)
    except ValueError:
        return None
    return days if days > 0 else None


@bp.get("/stats")
def stats_page():
    days = _parse_recent_days(request.args.get("days"))
    return render_template("stats.html", initial_days=days)


@bp.get("/api/stats/models")
def stats_models():
    ensure_image_tables()
    days = _parse_recent_days(request.args.get("days"))
    items = get_model_usage_counts(days)
    return jsonify({"items": items, "recent_days": days})


@bp.get("/api/stats/loras")
def stats_loras():
    ensure_image_tables()
    days = _parse_recent_days(request.args.get("days"))
    items = get_lora_usage_counts(days)
    return jsonify({"items": items, "recent_days": days})
