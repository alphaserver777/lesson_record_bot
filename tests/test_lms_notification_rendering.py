"""Exercise the pure renderer without creating Telegram or database clients."""
import ast
import html
from pathlib import Path
import unittest

source = Path(__file__).resolve().parents[1] / 'webapi/lms_notifications.py'
tree = ast.parse(source.read_text())
function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == '_message')
namespace = {'html': html}
exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), namespace)
render = namespace['_message']


class TestNotificationRendering(unittest.TestCase):
    def test_missing_optional_context_does_not_crash(self):
        payload = dict.fromkeys(['student', 'course', 'lesson', 'assignment', 'occurred_at'])
        payload['event_type'] = 'assignment.submitted'
        message, url = render(payload)
        self.assertNotIn('None', message)
        self.assertIn('Новая работа', message)
        self.assertTrue(url.startswith('https://'))

    def test_student_text_is_escaped(self):
        message, _ = render({'event_type': 'assignment.submitted', 'student': '<script>'})
        self.assertIn('&lt;script&gt;', message)
        self.assertNotIn('<script>', message)

    def test_lab_events_include_student_and_state(self):
        message, _ = render({'event_type': 'lab.reserved', 'student': 'Иван'})
        self.assertIn('стенд занят', message)
        self.assertIn('Иван', message)
        message, _ = render({'event_type': 'lab.released', 'student': 'Иван'})
        self.assertIn('стенд свободен', message)


if __name__ == '__main__':
    unittest.main()
