from __future__ import annotations

"""Utility script to upgrade the database schema."""

from settings import DB_PATH
from core.db.search_utils import ensure_image_tables


def upgrade() -> None:
    """Upgrade existing database to latest schema."""
    ensure_image_tables()


if __name__ == "__main__":
    upgrade()
    print(f"Database schema ensured at {DB_PATH}")
