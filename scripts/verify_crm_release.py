#!/usr/bin/env python3
"""Проверяет, что исходный код можно выпускать как CRM Professor IT."""

from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FRAGMENTS = {
    "database/connect.py": (
        "DATABASE_URL должен содержать URL PostgreSQL",
        "postgresql+asyncpg://",
    ),
    "webapi/main.py": (
        '@app.post("/api/auth/telegram/login-widget")',
        '@app.get("/api/admin/funnel/stages")',
        '@app.get("/api/admin/contacts")',
    ),
    "infra/ansible/templates/compose.yml.j2": (
        "database.env",
        "postgres:",
    ),
}


def main() -> int:
    problems: list[str] = []
    for relative_path, fragments in REQUIRED_FRAGMENTS.items():
        path = ROOT / relative_path
        if not path.is_file():
            problems.append(f"нет обязательного файла: {relative_path}")
            continue
        contents = path.read_text(encoding="utf-8")
        for fragment in fragments:
            if fragment not in contents:
                problems.append(f"в {relative_path} нет обязательного фрагмента: {fragment}")

    if problems:
        print("Выпуск остановлен: исходный код не является полным контуром CRM.", file=sys.stderr)
        for problem in problems:
            print(f"- {problem}", file=sys.stderr)
        return 1

    print("Проверка CRM пройдена.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
