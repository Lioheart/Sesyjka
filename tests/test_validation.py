from __future__ import annotations

import unittest

from sesyjka.validation import LANGUAGE_CHOICES, is_valid_isbn, normalize_language_choice


class ValidationTests(unittest.TestCase):
    def test_isbn_10_and_isbn_13_check_digits(self) -> None:
        self.assertTrue(is_valid_isbn("0-306-40615-2"))
        self.assertTrue(is_valid_isbn("978-83-7418-229-4"))
        self.assertTrue(is_valid_isbn("978-83-7418-230-0"))
        self.assertTrue(is_valid_isbn("978-83-7418-231-7"))
        self.assertTrue(is_valid_isbn("978-83-960121-1-1"))
        self.assertFalse(is_valid_isbn("978-83-7418-229-5"))
        self.assertFalse(is_valid_isbn("1234"))
        self.assertTrue(is_valid_isbn(""))

    def test_language_choices_and_legacy_aliases(self) -> None:
        self.assertEqual(
            LANGUAGE_CHOICES,
            ("PL", "ENG", "DE", "FR", "ES", "IT", "Inny"),
        )
        self.assertEqual(normalize_language_choice("EN"), "ENG")
        self.assertEqual(normalize_language_choice("Polski"), "PL")
        self.assertEqual(normalize_language_choice("JA"), "Inny")


if __name__ == "__main__":
    unittest.main()
