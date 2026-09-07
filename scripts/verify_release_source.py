#!/usr/bin/env python3
"""Проверяет, что к развёртыванию передана допустимая выпускная метка."""
from __future__ import annotations

import argparse
import re
import subprocess
import sys


def git(*args: str) -> str:
    return subprocess.check_output(("git", *args), text=True).strip()


def fail(message: str) -> None:
    print(f"Выпуск остановлен: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--require-main", action="store_true")
    args = parser.parse_args()

    if not re.fullmatch(r"professorit-v\d+\.\d+\.\d+", args.tag):
        fail("метка должна иметь вид professorit-vX.Y.Z")
    if not re.fullmatch(r"[0-9a-f]{40}", args.commit):
        fail("нужен полный SHA-1 фиксации")
    if git("status", "--porcelain"):
        fail("рабочая папка исходников не чиста")
    try:
        if git("cat-file", "-t", f"refs/tags/{args.tag}") != "tag":
            fail("метка должна быть аннотированной")
        tagged_commit = git("rev-parse", f"refs/tags/{args.tag}^{{commit}}")
    except subprocess.CalledProcessError:
        fail("выпускная метка не найдена")
    if tagged_commit != args.commit:
        fail("метка указывает на другую фиксацию")
    if git("rev-parse", "HEAD") != args.commit:
        fail("исходники не переключены на выпускную фиксацию")
    if args.require_main:
        try:
            subprocess.check_call(
                ("git", "merge-base", "--is-ancestor", args.commit, "origin/main"),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except subprocess.CalledProcessError:
            fail("выпускная фиксация не достижима из origin/main")
    print(f"Исходники выпуска {args.tag} ({args.commit}) проверены.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
