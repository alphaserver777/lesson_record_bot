import unittest

from webapi.prodamus import normalize_customer_email, sign_payload, verify_signature


class ProdamusSignatureTest(unittest.TestCase):
    def test_cyrillic_payload_is_signed_as_utf8(self) -> None:
        payload = {
            "customer_extra": "Тест-драйв профессии",
            "products": [
                {
                    "name": "Доступ к обучающим материалам",
                    "price": "1000",
                    "quantity": "1",
                }
            ],
        }

        signature = sign_payload(payload, "test-secret")

        self.assertEqual(
            signature,
            "93ced92569dce3e42359efb8a527d66b002711e7a9548ff3dfbf6204b5c33c8d",
        )
        self.assertTrue(verify_signature(payload, signature, "test-secret"))

    def test_customer_email_is_normalized_and_invalid_value_is_rejected(self) -> None:
        self.assertEqual(normalize_customer_email("  STUDENT@Example.RU "), "student@example.ru")
        self.assertIsNone(normalize_customer_email("not-an-email"))


if __name__ == "__main__":
    unittest.main()
