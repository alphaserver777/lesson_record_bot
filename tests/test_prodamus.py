import unittest

from webapi.prodamus import sign_payload, verify_signature


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
            "7e45cb7de48526a93d22da5dc4491280812d21b08f40be84bbd7a597e447e7fd",
        )
        self.assertTrue(verify_signature(payload, signature, "test-secret"))


if __name__ == "__main__":
    unittest.main()
