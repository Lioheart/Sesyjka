from __future__ import annotations

import gzip
import json
import zlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sesyjka.database_manager import DatabaseManager
from sesyjka.digital_resources import (
    DTRPG_LIBRARY_URL,
    DriveThruKeyStore,
    DriveThruLibraryItem,
    DriveThruRPGClient,
    match_rpg_item,
    scan_pdf_directory,
)
from sesyjka.repository import Repository


class DigitalResourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = DatabaseManager(self.root / "data")
        self.db.initialize()
        self.repo = Repository(self.db)
        game_system = self.repo.save_game_system({"nazwa": "Pathfinder 2e"})
        self.position_id = self.repo.save_system(
            {
                "nazwa": "Player Core",
                "typ": "Podręcznik Główny",
                "system_gry_id": game_system,
                "isbn": "9781640785533",
            }
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_digital_database_is_separate_and_initialized(self) -> None:
        path = self.db.own_root / "zasoby.db"
        self.assertTrue(path.is_file())
        with self.db.connect("zasoby.db") as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        self.assertTrue({"zasoby", "lokalizacje", "magazyny"}.issubset(tables))

    def test_storage_keeps_relative_path_and_resolves_file(self) -> None:
        library = self.root / "RPG"
        library.mkdir()
        pdf = library / "Pathfinder" / "Player Core.pdf"
        pdf.parent.mkdir()
        pdf.write_bytes(b"%PDF-1.4\nexample")
        storage_id = self.repo.save_storage_root(
            {"nazwa": "NAS RPG", "typ": "NAS", "sciezka_bazowa": str(library)}
        )
        resource_id = self.repo.save_digital_resource(
            {"pozycja_rpg_id": self.position_id, "typ": "PDF", "nazwa": "Player Core PDF"}
        )
        storage = next(row for row in self.repo.storage_roots() if row["id"] == storage_id)
        self.repo.save_resource_location(
            resource_id,
            {
                "typ": "Plik",
                "magazyn_uuid": storage["uuid"],
                "sciezka_wzgledna": "Pathfinder/Player Core.pdf",
                "preferowana": True,
            },
        )
        location = self.repo.resource_locations(resource_id)[0]
        self.assertEqual(location["sciezka_wzgledna"], "Pathfinder/Player Core.pdf")
        self.assertEqual(Path(location["sciezka_pelna"]), pdf)
        self.assertTrue(location["dostepny"])
        target = self.repo.best_resource_target(resource_id)
        self.assertEqual(target["kind"], "file")
        self.assertEqual(Path(target["value"]), pdf)

    def test_synced_storage_uuid_can_be_mapped_to_a_different_local_path(self) -> None:
        resource_id = self.repo.save_digital_resource({"typ": "PDF", "nazwa": "Remote PDF"})
        with self.db.connect("zasoby.db", write=True) as connection:
            connection.execute(
                "INSERT INTO lokalizacje (id, zasob_id, typ, magazyn_uuid, sciezka_wzgledna) VALUES (1, ?, 'Plik', 'shared-nas-uuid', 'Books/Remote.pdf')",
                (resource_id,),
            )
        missing = self.repo.unmapped_storage_roots()
        self.assertEqual(missing, [{"uuid": "shared-nas-uuid", "count": 1}])
        local_root = self.root / "other-mount"
        (local_root / "Books").mkdir(parents=True)
        (local_root / "Books" / "Remote.pdf").write_bytes(b"pdf")
        self.repo.save_storage_root(
            {
                "uuid": "shared-nas-uuid",
                "nazwa": "NAS on this computer",
                "typ": "NAS",
                "sciezka_bazowa": str(local_root),
            }
        )
        self.assertEqual(self.repo.unmapped_storage_roots(), [])
        self.assertTrue(self.repo.resource_locations(resource_id)[0]["dostepny"])

    def test_pdf_scanner_hashes_files_and_links_high_confidence_title(self) -> None:
        library = self.root / "PDF"
        library.mkdir()
        pdf = library / "Player_Core.pdf"
        pdf.write_bytes(b"%PDF-test")
        scanned = scan_pdf_directory(library, self.repo.systems())
        self.assertEqual(len(scanned), 1)
        self.assertEqual(scanned[0].suggested_rpg_id, self.position_id)
        self.assertEqual(len(scanned[0].sha256), 64)
        storage_id = self.repo.save_storage_root(
            {"nazwa": "PDF", "typ": "Lokalny", "sciezka_bazowa": str(library)}
        )
        report = self.repo.import_scanned_pdfs(storage_id, scanned)
        self.assertEqual(report["created"], 1)
        resource = self.repo.digital_resources()[0]
        self.assertEqual(resource["pozycja_rpg_id"], self.position_id)
        self.assertEqual(resource["dostepnosc"], "Dostępny lokalnie")

    def test_low_confidence_filename_is_not_linked(self) -> None:
        identifier, score = match_rpg_item("completely-unrelated-document.pdf", self.repo.systems())
        self.assertIsNone(identifier)
        self.assertLess(score, 0.9)

    def test_drivethru_library_link_uses_current_mylibrary_url(self) -> None:
        self.assertEqual(DTRPG_LIBRARY_URL, "https://www.drivethrurpg.com/en/mylibrary")

    def test_drivethru_key_store_is_owner_only_and_local(self) -> None:
        path = self.root / "config" / "drivethrurpg.json"
        store = DriveThruKeyStore(path)
        store.save("test-key")
        self.assertEqual(store.load(), "test-key")
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertIn("application_key", json.loads(path.read_text()))


    def test_drivethru_http_gzip_is_decoded_and_bearer_token_is_used(self) -> None:
        client = DriveThruRPGClient("key")
        raw = json.dumps({"ok": True}).encode("utf-8")
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        response.read.return_value = gzip.compress(raw)
        response.headers = {"Content-Encoding": "gzip", "Content-Type": "application/json"}
        with mock.patch("urllib.request.urlopen", return_value=response) as urlopen:
            payload = client._request_json("https://api.example.test", token="jwt-token")
        self.assertEqual(payload, {"ok": True})
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer jwt-token")
        self.assertEqual(request.get_header("Accept-encoding"), "identity")

    def test_drivethru_content_decoder_supports_gzip_magic_and_deflate(self) -> None:
        client = DriveThruRPGClient("key")
        raw = b'{"data":[]}'
        self.assertEqual(client._decode_content_encoding(gzip.compress(raw), ""), raw)
        self.assertEqual(client._decode_content_encoding(zlib.compress(raw), "deflate"), raw)

    def test_drivethru_jsonapi_response_uses_included_publisher(self) -> None:
        client = DriveThruRPGClient("key")
        payload = {
            "links": {"self": "/api/vBeta/order_products?page=1", "next": None},
            "meta": {"itemsPerPage": 50, "currentPage": 1},
            "data": [
                {
                    "id": "/api/vBeta/order_products/123",
                    "type": "OrderProduct",
                    "attributes": {
                        "orderProductId": 123,
                        "productId": 456,
                        "royaltyPublisherId": 367,
                        "name": "Player Core",
                        "isbn": "978-1-64078-553-3",
                        "files": [{"index": 0, "filename": "Player_Core.pdf", "size": 1024, "checksums": []}],
                    },
                }
            ],
            "included": [
                {
                    "id": "/api/vBeta/publishers/367",
                    "type": "Publisher",
                    "attributes": {"publisherId": 367, "name": "Paizo", "slug": "paizo"},
                }
            ],
        }
        parsed = client._parse_page(payload)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].publisher, "Paizo")
        self.assertEqual(parsed[0].title, "Player Core")

    def test_drivethru_current_list_format_is_supported(self) -> None:
        client = DriveThruRPGClient("key")
        payload = [
            {
                "productId": "456",
                "publisher": {"name": "Paizo"},
                "name": "Player Core",
                "orderProductId": 123,
                "fileLastModified": "2026-08-15T12:00:00Z",
                "files": [
                    {
                        "index": 7,
                        "filename": "Player_Core.pdf",
                        "checksums": [
                            {"checksum": "a" * 64, "checksumDate": "2026-08-15"}
                        ],
                    }
                ],
            }
        ]
        parsed = client._parse_page(payload)
        self.assertEqual(len(parsed), 1)
        item = parsed[0]
        self.assertEqual(item.order_product_id, 123)
        self.assertEqual(item.product_id, 456)
        self.assertEqual(item.title, "Player Core")
        self.assertEqual(item.publisher, "Paizo")
        self.assertEqual(item.filename, "Player_Core.pdf")
        self.assertEqual(item.sha256, "a" * 64)
        self.assertEqual(item.resource_type, "PDF")
        self.assertEqual(item.product_url, "https://www.drivethrurpg.com/en/product/456")

    def test_drivethru_library_paginates_current_list_until_empty_page(self) -> None:
        client = DriveThruRPGClient("key")
        pages = [
            [{"productId": "1", "name": "One", "orderProductId": 11, "files": []}],
            [{"productId": "2", "name": "Two", "orderProductId": 22, "files": []}],
            [],
        ]
        with mock.patch.object(client, "authenticate", return_value="token"), mock.patch.object(
            client, "_request_json", side_effect=pages
        ) as request:
            result = client.library(page_size=100)
        self.assertEqual([item.title for item in result], ["One", "Two"])
        self.assertEqual(request.call_count, 3)
        first_url = request.call_args_list[0].args[0]
        self.assertIn("pageSize=50", first_url)
        self.assertIn("library=true", first_url)
        self.assertIn("getFilters=0", first_url)

    def test_drivethru_page_parser_imports_metadata_and_product_link(self) -> None:
        client = DriveThruRPGClient("key")
        payload = {
            "data": [
                {
                    "id": "123",
                    "attributes": {
                        "orderProductId": 123,
                        "productId": 456,
                        "name": "Player Core",
                        "isbn": "978-1-64078-553-3",
                        "datePurchased": "2026-01-02",
                        "publisher": {"name": "Paizo"},
                        "files": [
                            {
                                "index": 7,
                                "filename": "Player_Core.pdf",
                                "size": 1024,
                                "checksums": [{"checksum": "a" * 64}],
                            }
                        ],
                    },
                }
            ]
        }
        parsed = client._parse_page(payload)
        self.assertEqual(len(parsed), 1)
        item = parsed[0]
        self.assertEqual(item.resource_type, "PDF")
        self.assertEqual(item.publisher, "Paizo")
        self.assertEqual(item.sha256, "a" * 64)
        self.assertEqual(item.product_url, "https://www.drivethrurpg.com/en/product/456")
        report = self.repo.import_drivethru_library(parsed)
        self.assertEqual(report["created"], 1)
        self.assertEqual(report["linked"], 1)
        resource = self.repo.digital_resources()[0]
        self.assertEqual(resource["dostawca"], "DriveThruRPG")
        self.assertEqual(resource["pozycja_rpg_id"], self.position_id)
        target = self.repo.best_resource_target(int(resource["id"]))
        self.assertEqual(target["kind"], "url")

    def test_drivethru_import_is_idempotent(self) -> None:
        item = DriveThruLibraryItem(
            external_id="dtrpg:123:1",
            order_product_id=123,
            product_id=456,
            file_index=1,
            title="Player Core",
            filename="Player_Core.pdf",
            size=200,
            sha256="b" * 64,
            isbn="9781640785533",
            publisher="Paizo",
            product_url="https://www.drivethrurpg.com/en/product/456",
            resource_type="PDF",
            format_name="PDF",
            date_purchased="2026-01-01",
        )
        first = self.repo.import_drivethru_library([item])
        second = self.repo.import_drivethru_library([item])
        self.assertEqual(first["created"], 1)
        self.assertEqual(second["created"], 0)
        self.assertEqual(second["updated"], 1)
        self.assertEqual(len(self.repo.digital_resources()), 1)


if __name__ == "__main__":
    unittest.main()
