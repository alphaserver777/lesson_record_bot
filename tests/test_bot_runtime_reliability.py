"""Проверяет контракт жизненного цикла без запуска Telegram и PostgreSQL."""
import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def function(path: Path, name: str):
    tree = ast.parse(path.read_text())
    return next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == name)


def calls(node):
    return [
        item.func.attr if isinstance(item.func, ast.Attribute) else item.func.id
        for item in ast.walk(node)
        if isinstance(item, ast.Call) and isinstance(item.func, (ast.Attribute, ast.Name))
    ]


class TestBotRuntimeReliability(unittest.TestCase):
    def test_scheduler_releases_database_session_between_passes(self):
        scheduler = function(ROOT / "utils/restart_services.py", "_restarting_services_loop")
        names = calls(scheduler)
        self.assertIn("remove_session", names)
        self.assertLess(names.index("remove_session"), names.index("sleep"))

    def test_shutdown_closes_services_and_preserves_pending_updates(self):
        main = function(ROOT / "main.py", "main")
        names = calls(main)
        self.assertIn("create_task", names)
        self.assertIn("cancel", names)
        self.assertIn("close_db", names)
        delete = next(item for item in ast.walk(main) if isinstance(item, ast.Call) and isinstance(item.func, ast.Attribute) and item.func.attr == "delete_webhook")
        value = next(keyword.value for keyword in delete.keywords if keyword.arg == "drop_pending_updates")
        self.assertIsInstance(value, ast.Constant)
        self.assertFalse(value.value)


if __name__ == "__main__":
    unittest.main()
