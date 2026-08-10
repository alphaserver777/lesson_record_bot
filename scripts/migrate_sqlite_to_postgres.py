#!/usr/bin/env python3
"""One-way, verified import of the legacy SQLite application database.

The target PostgreSQL database must be empty. The script never deletes or
changes the source file, and refuses to overwrite a target table. Run it with:

  DATABASE_URL='postgresql://user:password@host:5432/proffessor_it' \
    python scripts/migrate_sqlite_to_postgres.py /path/to/database.db
"""
from __future__ import annotations

import asyncio
import datetime as dt
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

# When executed as ``python scripts/...``, Python adds ``scripts/`` rather
# than the project root to sys.path. Make imports work both locally and inside
# the migration container without requiring a package installation.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import text

from database.connect import Base, engine
import database.models  # noqa: F401 - registers all tables in Base.metadata


TABLES = (
    "student_profiles",
    "record_dates",
    "regular_lessons",
    "regular_lesson_exceptions",
    "date_availability_overrides",
    "payments",
    "analytics_events",
    "working_intervals",
    "admin_audit_log",
)
DATE_COLUMNS = {"record_date", "lesson_date", "exception_date", "target_date", "related_slot_date"}
BOOLEAN_COLUMNS = {"blocked", "is_deleted", "is_active"}


def source_rows(source: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    found = source.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    if not found:
        return []
    source.row_factory = sqlite3.Row
    return [dict(row) for row in source.execute(f'SELECT * FROM "{table}"')]


def normalize(row: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in row.items():
        if value is not None and key in DATE_COLUMNS and isinstance(value, str):
            value = dt.date.fromisoformat(value)
        elif value is not None and key in BOOLEAN_COLUMNS:
            value = bool(value)
        result[key] = value
    return result


def add_archived_profiles(rows_by_table: dict[str, list[dict[str, Any]]]) -> int:
    """Preserve legacy facts whose profile was deleted in SQLite.

    SQLite did not enforce its foreign keys consistently. PostgreSQL does, so
    a minimal soft-deleted profile is created for every historical Telegram ID
    still referenced by lessons, payments or analytics.
    """
    profiles = rows_by_table["student_profiles"]
    existing_ids = {row.get("telegram_id") for row in profiles if row.get("telegram_id") is not None}
    referenced_ids: set[int] = set()
    for table in ("record_dates", "regular_lessons", "payments", "analytics_events"):
        for row in rows_by_table[table]:
            telegram_id = row.get("telegram_id")
            if telegram_id is not None:
                referenced_ids.add(int(telegram_id))

    missing_ids = sorted(referenced_ids - {int(item) for item in existing_ids})
    profiles.extend(
        {
            "telegram_id": telegram_id,
            "full_name": "Архивный профиль",
            "blocked": 1,
            "is_deleted": 1,
            "balance_lessons": 0,
        }
        for telegram_id in missing_ids
    )
    return len(missing_ids)


async def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: migrate_sqlite_to_postgres.py /absolute/path/to/database.db", file=sys.stderr)
        return 2
    if not engine.url.drivername.startswith("postgresql+"):
        print("DATABASE_URL must point to PostgreSQL.", file=sys.stderr)
        return 2

    sqlite_path = Path(sys.argv[1]).resolve()
    if not sqlite_path.is_file():
        print(f"SQLite file not found: {sqlite_path}", file=sys.stderr)
        return 2

    source = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    try:
        rows_by_table = {table: source_rows(source, table) for table in TABLES}
        archived_profiles = add_archived_profiles(rows_by_table)
        expected_counts = {table: len(rows_by_table[table]) for table in TABLES}
        async with engine.begin() as target:
            await target.run_sync(Base.metadata.create_all)
            for table in TABLES:
                target_count = int((await target.execute(text(f'SELECT COUNT(*) FROM "{table}"'))).scalar_one())
                if target_count:
                    raise RuntimeError(f'Target table "{table}" is not empty ({target_count} rows); import stopped.')

            for table in TABLES:
                rows = rows_by_table[table]
                if not rows:
                    continue
                target_columns = set(Base.metadata.tables[table].c.keys())
                prepared_rows = [
                    {key: value for key, value in normalize(row).items() if key in target_columns}
                    for row in rows
                ]
                columns_list = sorted({column for row in prepared_rows for column in row})
                # executemany requires every parameter group to contain the
                # same keys. Legacy archival rows intentionally have only a
                # few values, so make absent optional fields explicit NULL.
                prepared_rows = [
                    {column: row.get(column) for column in columns_list}
                    for row in prepared_rows
                ]
                columns = ", ".join(f'"{column}"' for column in columns_list)
                values = ", ".join(f':{column}' for column in columns_list)
                statement = text(f'INSERT INTO "{table}" ({columns}) VALUES ({values})')
                await target.execute(statement, prepared_rows)

            for table in TABLES:
                if "id" not in Base.metadata.tables[table].c:
                    continue
                await target.execute(text(
                    f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                    f"GREATEST((SELECT COALESCE(MAX(id), 1) FROM \"{table}\"), 1), true)"
                ))

            target_counts = {
                table: int((await target.execute(text(f'SELECT COUNT(*) FROM "{table}"'))).scalar_one())
                for table in TABLES
            }
        if expected_counts != target_counts:
            raise RuntimeError(f"Count mismatch: expected={expected_counts}, target={target_counts}")
        print("Migration verified. Rows by table:")
        for table in TABLES:
            print(f"  {table}: {target_counts[table]}")
        if archived_profiles:
            print(f"  archived profiles added for legacy references: {archived_profiles}")
        return 0
    finally:
        source.close()
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
