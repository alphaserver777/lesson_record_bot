import unittest
from unittest.mock import patch

from webapi.lms_provisioning import generate_temporary_password


class TemporaryPasswordTest(unittest.TestCase):
    def test_password_has_requested_length_and_safe_alphabet(self):
        with patch("webapi.lms_provisioning.secrets.choice", side_effect=lambda alphabet: alphabet[0]):
            password = generate_temporary_password(14)
        self.assertEqual(password, "A" * 14)
        self.assertEqual(len(password), 14)


if __name__ == "__main__":
    unittest.main()
