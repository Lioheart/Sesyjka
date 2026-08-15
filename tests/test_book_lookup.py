from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sesyjka import book_lookup


class BookLookupTests(unittest.TestCase):
    def test_normalize_isbn_removes_separators(self) -> None:
        self.assertEqual(book_lookup.normalize_isbn("83-86187-76-x"), "838618776X")
        self.assertEqual(book_lookup.normalize_isbn("978-83-7418-231-7"), "9788374182317")

    def test_open_library_uses_matching_edition_title_year_and_cover(self) -> None:
        payload = {
            "docs": [
                {
                    "title": "Work title",
                    "first_publish_year": 1980,
                    "cover_i": 100,
                    "editions": {
                        "docs": [
                            {
                                "title": "Polskie wydanie",
                                "publish_date": "1989",
                                "cover_i": 321,
                                "isbn": ["838618776X"],
                            }
                        ]
                    },
                }
            ]
        }
        with patch.object(book_lookup, "_json_get", return_value=payload):
            result = book_lookup._open_library_result("838618776X", timeout=1)
        assert result is not None
        self.assertEqual(result.title, "Polskie wydanie")
        self.assertEqual(result.published_year, "1989")
        self.assertIn("/id/321-L.jpg", result.cover_url)
        self.assertEqual(result.metadata_sources, ("Open Library",))

    def test_google_books_extracts_online_price(self) -> None:
        payload = {
            "items": [
                {
                    "volumeInfo": {
                        "title": "Example RPG",
                        "publishedDate": "2024-05-17",
                        "imageLinks": {"large": "http://books.google.test/cover.jpg"},
                    },
                    "saleInfo": {
                        "isEbook": True,
                        "retailPrice": {"amount": 42.5, "currencyCode": "PLN"},
                    },
                }
            ]
        }
        with patch.object(book_lookup, "_json_get", return_value=payload):
            result = book_lookup._google_books_result("9780000000000", timeout=1)
        assert result is not None
        self.assertEqual(result.title, "Example RPG")
        self.assertEqual(result.published_year, "2024")
        self.assertEqual(result.price_amount, 42.5)
        self.assertEqual(result.price_currency, "PLN")
        self.assertEqual(result.price_kind, "e-book")
        self.assertTrue(result.cover_url.startswith("https://"))

    def test_lookup_merges_open_library_metadata_with_google_price(self) -> None:
        ol = book_lookup.BookLookupResult(
            isbn="123",
            title="OL title",
            published_year="2001",
            cover_url="https://openlibrary.test/cover.jpg",
            metadata_sources=("Open Library",),
        )
        google = book_lookup.BookLookupResult(
            isbn="123",
            title="Google title",
            published_year="2002",
            price_amount=29.99,
            price_currency="EUR",
            price_kind="e-book",
            price_source="Google Books",
            metadata_sources=("Google Books",),
        )
        with patch.object(book_lookup, "_open_library_result", return_value=ol), patch.object(
            book_lookup, "_google_books_result", return_value=google
        ):
            result = book_lookup.lookup_book("123", timeout=1)
        self.assertEqual(result.title, "OL title")
        self.assertEqual(result.published_year, "2001")
        self.assertEqual(result.price_amount, 29.99)
        self.assertEqual(result.price_currency, "EUR")
        self.assertEqual(result.metadata_sources, ("Open Library", "Google Books"))

    def test_cover_cache_uses_xdg_cache_override(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"SESYJKA_CACHE_DIR": directory}
        ):
            path = book_lookup.cover_cache_path("978-83-7418-231-7")
            self.assertEqual(path.parent, Path(directory) / "covers")
            self.assertEqual(path.name, "9788374182317.jpg")


if __name__ == "__main__":
    unittest.main()
