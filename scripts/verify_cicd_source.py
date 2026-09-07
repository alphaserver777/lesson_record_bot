#!/usr/bin/env python3
"""Быстрая проверка отслеживаемых файлов перед удалёнными проверками."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


FORBIDDEN_FILE_NAMES = {".env", "id_rsa", "id_ed25519", "credentials.json"}
SECRET_MARKERS = (
    "-----BEGIN " + "PRIVATE KEY-----",
    "-----BEGIN " + "OPENSSH PRIVATE KEY-----",
    "-----BEGIN " + "RSA PRIVATE KEY-----",
    "gh" + "p_",
    "github" + "_pat_",
)


def main() -> int:
    tracked = subprocess.check_output(("git", "ls-files"), text=True).splitlines()
    problems: list[str] = []
    for relative in tracked:
        path = Path(relative)
        # При локальной проверке до добавления в индекс удалённый файл ещё может
        # присутствовать в выводе git ls-files. В чистой CI-папке такого случая нет.
        if not path.is_file():
            continue
        if path.name in FORBIDDEN_FILE_NAMES:
            problems.append(f"запрещённый файл: {relative}")
            continue
        try:
            contents = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if any(marker in contents for marker in SECRET_MARKERS):
            problems.append(f"возможный секрет: {relative}")
    if problems:
        print("Проверка безопасности не пройдена:", file=sys.stderr)
        for problem in problems:
            print(f"- {problem}", file=sys.stderr)
        return 1
    print("Проверка исходников конвейера пройдена.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
