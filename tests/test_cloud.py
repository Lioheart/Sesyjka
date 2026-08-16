from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

from sesyjka.cloud import (
    CloudConfig,
    CloudService,
    CloudSession,
    SessionTokenStore,
    SupabaseHttpClient,
)
from sesyjka.database_manager import DatabaseManager
from sesyjka.repository import Repository


class FakeSupabaseClient:
    def __init__(self) -> None:
        self.records: dict[tuple[str, str], dict[str, Any]] = {}
        self.fetch_since_calls: list[str | None] = []
        self.upsert_calls: list[tuple[str, str]] = []
        self._clock = 0

    def _next_timestamp(self) -> str:
        self._clock += 1
        return f"2026-08-15T00:00:{self._clock:02d}Z"

    def fetch_records(
        self, token: str, user_id: str, updated_since: str | None = None
    ) -> list[dict[str, Any]]:
        self.fetch_since_calls.append(updated_since)
        rows = [dict(row) for row in self.records.values() if row["owner_id"] == user_id]
        if updated_since:
            rows = [row for row in rows if str(row.get("updated_at") or "") >= updated_since]
        return rows

    def fetch_record(
        self, token: str, user_id: str, entity_type: str, record_key: str
    ) -> dict[str, Any] | None:
        row = self.records.get((entity_type, record_key))
        if row is None or row["owner_id"] != user_id:
            return None
        return dict(row)

    def upsert_record(
        self,
        token: str,
        user_id: str,
        *,
        entity_type: str,
        record_key: str,
        payload: dict[str, Any] | None,
        deleted: bool,
        version: int,
        device_id: str,
    ) -> dict[str, Any]:
        row = {
            "id": f"{entity_type}-{record_key}",
            "owner_id": user_id,
            "entity_type": entity_type,
            "record_key": record_key,
            "payload": dict(payload or {}),
            "version": int(version),
            "deleted": bool(deleted),
            "updated_at": self._next_timestamp(),
            "device_id": device_id,
        }
        self.records[(entity_type, record_key)] = row
        self.upsert_calls.append((entity_type, record_key))
        return dict(row)


class CloudSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = DatabaseManager(self.root / "data")
        self.db.initialize()
        self.repo = Repository(self.db)
        self.token_store = SessionTokenStore(self.root / "session.json")
        self.cloud = CloudService(self.db, token_store=self.token_store)
        self.cloud._session = CloudSession(
            access_token="header.payload.signature",
            refresh_token="refresh",
            expires_at=int(time.time()) + 3600,
            user_id="11111111-1111-1111-1111-111111111111",
            email="test@example.com",
        )
        self.fake = FakeSupabaseClient()
        self.cloud._client = lambda _url, _key: self.fake  # type: ignore[method-assign]
        self.url = "https://example.supabase.co"
        self.key = "sb_publishable_abcdefghijklmnopqrstuvwxyz"

    def tearDown(self) -> None:
        self.temp.cleanup()


    def _schema_signature(self) -> dict[str, list[tuple[str, str]]]:
        signature: dict[str, list[tuple[str, str]]] = {}
        for filename in (
            "systemy_rpg.db",
            "sesje_rpg.db",
            "gracze.db",
            "wydawcy.db",
            "planszowe.db",
        ):
            with self.db.connect(filename) as connection:
                rows = connection.execute(
                    "SELECT name, COALESCE(sql, '') FROM sqlite_master "
                    "WHERE type IN ('table', 'index', 'trigger') AND name NOT LIKE 'sqlite_%' ORDER BY type, name"
                ).fetchall()
                signature[filename] = [(str(row["name"]), str(row[1])) for row in rows]
        return signature

    def test_sync_db_is_separate_from_original_databases(self) -> None:
        self.assertTrue((self.db.own_root / "sync.db").is_file())
        original = {
            "systemy_rpg.db",
            "sesje_rpg.db",
            "gracze.db",
            "wydawcy.db",
            "planszowe.db",
            "zasoby.db",
        }
        self.assertEqual({p.name for p in self.db.own_root.glob("*.db")} - {"sync.db"}, original)

    def test_digital_resources_sync_but_device_storage_mappings_do_not(self) -> None:
        game_system_id = self.repo.save_game_system({"nazwa": "System"})
        position_id = self.repo.save_system(
            {"nazwa": "Book", "typ": "Podręcznik Główny", "system_gry_id": game_system_id}
        )
        storage_root = self.root / "library"
        storage_root.mkdir()
        storage_id = self.repo.save_storage_root(
            {"nazwa": "Laptop", "typ": "Lokalny", "sciezka_bazowa": str(storage_root)}
        )
        storage = next(item for item in self.repo.storage_roots() if item["id"] == storage_id)
        resource_id = self.repo.save_digital_resource(
            {"pozycja_rpg_id": position_id, "typ": "PDF", "nazwa": "Book PDF"}
        )
        self.repo.save_resource_location(
            resource_id,
            {"typ": "Plik", "magazyn_uuid": storage["uuid"], "sciezka_wzgledna": "Book.pdf"},
        )
        self.cloud.sync(self.url, self.key)
        self.assertIn(("digital_resources", str(resource_id)), self.fake.records)
        self.assertTrue(any(key[0] == "digital_locations" for key in self.fake.records))
        self.assertFalse(any(key[0] == "digital_storages" for key in self.fake.records))

    def test_initial_local_records_are_uploaded(self) -> None:
        publisher_id = self.repo.save_publisher({"nazwa": "Test Publisher", "kraj": "PL", "strona": ""})
        report = self.cloud.sync(self.url, self.key)
        self.assertGreaterEqual(report.uploaded, 1)
        remote = self.fake.records[("publishers", str(publisher_id))]
        self.assertEqual(remote["payload"]["nazwa"], "Test Publisher")
        self.assertFalse(remote["deleted"])

    def test_remote_record_is_downloaded_into_local_sqlite(self) -> None:
        self.fake.records[("publishers", "42")] = {
            "id": "remote-42",
            "owner_id": self.cloud.session.user_id,
            "entity_type": "publishers",
            "record_key": "42",
            "payload": {"id": 42, "nazwa": "Cloud Publisher", "strona": "https://example.com", "kraj": "PL"},
            "version": 1,
            "deleted": False,
            "updated_at": "2026-08-15T00:00:00Z",
            "device_id": "other",
        }
        report = self.cloud.sync(self.url, self.key)
        self.assertGreaterEqual(report.downloaded, 1)
        rows = [row for row in self.repo.publishers() if int(row["id"]) == 42]
        self.assertEqual(rows[0]["nazwa"], "Cloud Publisher")

    def test_remote_legacy_group_metadata_is_not_reintroduced_locally(self) -> None:
        game_system_id = self.repo.save_game_system({"nazwa": "System grup"})
        self.cloud.sync(self.url, self.key)
        self.fake.records[("rpg_items", "777")] = {
            "id": "remote-rpg-group-777",
            "owner_id": self.cloud.session.user_id,
            "entity_type": "rpg_items",
            "record_key": "777",
            "payload": {
                "id": 777,
                "nazwa": "Grupa z chmury",
                "typ": "Grupa",
                "system_gry_id": game_system_id,
                "wydawca_id": 55,
                "fizyczny": 1,
                "pdf": 1,
                "jezyk": "PL",
                "status_gra": "Grane",
                "status_kolekcja": "W kolekcji",
                "cena_zakupu": 99.0,
                "waluta_zakupu": "PLN",
                "vtt": "Foundry VTT",
                "rok_wydania": 2024,
                "isbn": "legacy",
            },
            "version": 1,
            "deleted": False,
            "updated_at": "2026-08-15T00:00:59Z",
            "device_id": "old-client",
        }
        report = self.cloud.sync(self.url, self.key)
        self.assertGreaterEqual(report.downloaded, 1)
        group = next(row for row in self.repo.systems() if int(row["id"]) == 777)
        self.assertEqual(group["nazwa"], "Grupa z chmury")
        self.assertEqual(group["system_gry_id"], game_system_id)
        self.assertEqual(group["fizyczny"], 0)
        self.assertEqual(group["pdf"], 0)
        for key in (
            "wydawca_id", "jezyk", "status_gra", "status_kolekcja",
            "cena_zakupu", "waluta_zakupu", "vtt", "rok_wydania", "isbn",
        ):
            self.assertIsNone(group[key], key)

    def test_local_database_wins_when_both_sides_changed(self) -> None:
        publisher_id = self.repo.save_publisher({"nazwa": "Start", "kraj": "PL", "strona": ""})
        self.cloud.sync(self.url, self.key)
        self.repo.save_publisher({"nazwa": "Lokalna", "kraj": "PL", "strona": ""}, publisher_id)
        row = self.fake.records[("publishers", str(publisher_id))]
        row["payload"] = {**row["payload"], "nazwa": "Chmurowa"}
        row["version"] = 2
        row["updated_at"] = "2026-08-15T00:00:59Z"
        report = self.cloud.sync(self.url, self.key)
        self.assertGreaterEqual(report.uploaded, 1)
        self.assertEqual(report.conflicts, 0)
        self.assertEqual(self.cloud.conflicts, [])
        self.assertEqual(
            self.fake.records[("publishers", str(publisher_id))]["payload"]["nazwa"],
            "Lokalna",
        )
        current = [row for row in self.repo.publishers() if int(row["id"]) == publisher_id][0]
        self.assertEqual(current["nazwa"], "Lokalna")

    def test_existing_conflict_is_closed_with_local_priority(self) -> None:
        publisher_id = self.repo.save_publisher({"nazwa": "Start", "kraj": "PL", "strona": ""})
        self.cloud.sync(self.url, self.key)
        self.repo.save_publisher({"nazwa": "Lokalna", "kraj": "PL", "strona": ""}, publisher_id)
        row = self.fake.records[("publishers", str(publisher_id))]
        row["payload"] = {**row["payload"], "nazwa": "Chmurowa"}
        row["version"] = 2
        row["updated_at"] = "2026-08-15T00:00:59Z"
        self.cloud.store.record_conflict(
            "publishers", str(publisher_id),
            {"id": publisher_id, "nazwa": "Lokalna"},
            {"id": publisher_id, "nazwa": "Chmurowa"},
            False, False, 2,
        )
        self.cloud.sync(self.url, self.key)
        self.assertEqual(self.cloud.conflicts, [])
        self.assertEqual(
            self.fake.records[("publishers", str(publisher_id))]["payload"]["nazwa"],
            "Lokalna",
        )

    def test_local_deletion_is_uploaded_as_tombstone(self) -> None:
        publisher_id = self.repo.save_publisher({"nazwa": "Do usunięcia", "kraj": "PL", "strona": ""})
        self.cloud.sync(self.url, self.key)
        self.repo.delete_publisher(publisher_id)
        report = self.cloud.sync(self.url, self.key)
        self.assertGreaterEqual(report.deleted_remote, 1)
        self.assertTrue(self.fake.records[("publishers", str(publisher_id))]["deleted"])


    def test_cloud_sync_does_not_change_original_database_schemas(self) -> None:
        before = self._schema_signature()
        self.repo.save_publisher({"nazwa": "Schema Test", "kraj": "PL", "strona": ""})
        self.cloud.sync(self.url, self.key)
        self.fake.records[("publishers", "99")] = {
            "id": "remote-99",
            "owner_id": self.cloud.session.user_id,
            "entity_type": "publishers",
            "record_key": "99",
            "payload": {"id": 99, "nazwa": "Remote Schema Test", "strona": "", "kraj": "PL"},
            "version": 1,
            "deleted": False,
            "updated_at": "2026-08-15T00:00:00Z",
            "device_id": "other",
        }
        self.cloud.sync(self.url, self.key)
        self.assertEqual(self._schema_signature(), before)

    def test_switching_cloud_user_discards_previous_sync_mappings(self) -> None:
        publisher_id = self.repo.save_publisher({"nazwa": "Account Test", "kraj": "PL", "strona": ""})
        self.cloud.sync(self.url, self.key)
        self.assertIsNotNone(self.cloud.store.mapping("publishers", str(publisher_id)))
        self.cloud._session = CloudSession(
            access_token="other.payload.signature",
            refresh_token="other-refresh",
            expires_at=int(time.time()) + 3600,
            user_id="22222222-2222-2222-2222-222222222222",
            email="other@example.com",
        )
        self.fake.records.clear()
        self.cloud.sync(self.url, self.key)
        self.assertEqual(self.cloud.store.get_meta("last_sync_user"), self.cloud.session.user_id)
        remote = self.fake.records[("publishers", str(publisher_id))]
        self.assertEqual(remote["owner_id"], self.cloud.session.user_id)

    def test_missing_remote_row_never_deletes_local_record(self) -> None:
        publisher_id = self.repo.save_publisher({"nazwa": "Local Safe", "kraj": "PL", "strona": ""})
        self.cloud.sync(self.url, self.key)
        del self.fake.records[("publishers", str(publisher_id))]

        self.cloud.sync(self.url, self.key)
        self.assertEqual(self.repo.publishers()[0]["nazwa"], "Local Safe")

        # A later local edit marks the database dirty and recreates a backend row
        # that was physically removed without the supported tombstone mechanism.
        self.repo.save_publisher(
            {"nazwa": "Local Safe 2", "kraj": "PL", "strona": ""}, publisher_id
        )
        report = self.cloud.sync(self.url, self.key)
        self.assertGreaterEqual(report.uploaded, 1)
        self.assertIn(("publishers", str(publisher_id)), self.fake.records)
        self.assertEqual(
            self.fake.records[("publishers", str(publisher_id))]["payload"]["nazwa"],
            "Local Safe 2",
        )

    def test_failed_remote_apply_rolls_back_publishers_and_sync_state(self) -> None:
        publisher_id = self.repo.save_publisher({"nazwa": "Do ochrony", "kraj": "PL", "strona": ""})
        self.cloud.sync(self.url, self.key)
        before_mapping = self.cloud.store.mapping("publishers", str(publisher_id))
        self.assertIsNotNone(before_mapping)
        before_remote_hash = str(before_mapping["last_remote_hash"])

        publisher_row = self.fake.records[("publishers", str(publisher_id))]
        publisher_row["payload"] = {}
        publisher_row["deleted"] = True
        publisher_row["version"] = 2
        self.fake.records[("digital_locations", "999")] = {
            "id": "digital_locations-999",
            "owner_id": self.cloud.session.user_id,
            "entity_type": "digital_locations",
            "record_key": "999",
            "payload": {
                "id": 999,
                "zasob_id": 123456,
                "typ": "DriveThruRPG",
                "url": "https://example.invalid",
                "preferowana": 0,
                "ostatnio_dostepny": 1,
            },
            "version": 1,
            "deleted": False,
            "updated_at": "2026-08-15T00:00:00Z",
            "device_id": "other",
        }

        with self.assertRaisesRegex(Exception, "Lokalne bazy przywrócono"):
            self.cloud.sync(self.url, self.key)

        publishers = self.repo.publishers()
        self.assertEqual(len(publishers), 1)
        self.assertEqual(publishers[0]["nazwa"], "Do ochrony")
        restored_mapping = self.cloud.store.mapping("publishers", str(publisher_id))
        self.assertIsNotNone(restored_mapping)
        self.assertEqual(str(restored_mapping["last_remote_hash"]), before_remote_hash)


    def test_local_writes_are_queued_without_running_sync(self) -> None:
        self.assertEqual(self.cloud.pending_local_databases, ())
        self.repo.save_publisher({"nazwa": "Queued", "kraj": "PL", "strona": ""})
        self.assertIn("wydawcy.db", self.cloud.pending_local_databases)
        self.assertEqual(self.fake.fetch_since_calls, [])
        self.assertEqual(self.fake.upsert_calls, [])

    def test_incremental_sync_uses_remote_cursor_and_uploads_only_changed_record(self) -> None:
        first_id = self.repo.save_publisher({"nazwa": "One", "kraj": "PL", "strona": ""})
        second_id = self.repo.save_publisher({"nazwa": "Two", "kraj": "PL", "strona": ""})
        self.cloud.sync(self.url, self.key)
        # The first local-only pass cannot establish a safe remote cursor from its
        # own writes, so the next pass performs one complete remote read.
        self.cloud.sync(self.url, self.key)
        self.assertIsNotNone(self.cloud.store.get_meta("remote_cursor_at"))

        self.fake.upsert_calls.clear()
        self.repo.save_publisher({"nazwa": "One changed", "kraj": "PL", "strona": ""}, first_id)
        report = self.cloud.sync(self.url, self.key)

        self.assertIsNotNone(self.fake.fetch_since_calls[-1])
        self.assertIn(("publishers", str(first_id)), self.fake.upsert_calls)
        self.assertNotIn(("publishers", str(second_id)), self.fake.upsert_calls)
        self.assertEqual(report.uploaded, 1)

    def test_incremental_sync_scans_only_locally_changed_database(self) -> None:
        publisher_id = self.repo.save_publisher({"nazwa": "One", "kraj": "PL", "strona": ""})
        self.cloud.sync(self.url, self.key)
        self.cloud.sync(self.url, self.key)

        captured: list[set[str] | None] = []
        original = self.cloud._local_snapshot

        def wrapped(db_files: set[str] | None = None):
            captured.append(None if db_files is None else set(db_files))
            return original(db_files)

        self.cloud._local_snapshot = wrapped  # type: ignore[method-assign]
        self.repo.save_publisher({"nazwa": "Changed", "kraj": "PL", "strona": ""}, publisher_id)
        self.cloud.sync(self.url, self.key)
        self.assertIn({"wydawcy.db"}, captured)
        self.assertNotIn(None, captured)

    def test_external_sqlite_edit_is_detected_by_fingerprint(self) -> None:
        publisher_id = self.repo.save_publisher({"nazwa": "Before", "kraj": "PL", "strona": ""})
        self.cloud.sync(self.url, self.key)
        self.cloud.sync(self.url, self.key)
        self.assertEqual(self.cloud.pending_local_databases, ())

        import sqlite3
        with sqlite3.connect(self.db.own_root / "wydawcy.db") as connection:
            connection.execute("UPDATE wydawcy SET nazwa='External' WHERE id=?", (publisher_id,))
            connection.commit()

        self.fake.upsert_calls.clear()
        report = self.cloud.sync(self.url, self.key)
        self.assertEqual(report.uploaded, 1)
        self.assertIn(("publishers", str(publisher_id)), self.fake.upsert_calls)
        self.assertEqual(
            self.fake.records[("publishers", str(publisher_id))]["payload"]["nazwa"],
            "External",
        )

    def test_remote_apply_does_not_requeue_database_as_local_change(self) -> None:
        self.fake.records[("publishers", "42")] = {
            "id": "remote-42",
            "owner_id": self.cloud.session.user_id,
            "entity_type": "publishers",
            "record_key": "42",
            "payload": {"id": 42, "nazwa": "Remote only", "strona": "", "kraj": "PL"},
            "version": 1,
            "deleted": False,
            "updated_at": "2026-08-15T00:00:10Z",
            "device_id": "other",
        }
        self.cloud.sync(self.url, self.key)
        self.assertEqual(self.cloud.pending_local_databases, ())

    def test_session_store_uses_owner_only_permissions(self) -> None:
        session = CloudSession("access", "refresh", 123, "uid", "u@example.com")
        self.token_store.save(session)
        mode = os.stat(self.token_store.path).st_mode & 0o777
        self.assertEqual(mode, 0o600)
        loaded = self.token_store.load()
        self.assertEqual(loaded.email, "u@example.com")
        self.token_store.clear()
        self.assertFalse(self.token_store.path.exists())


class SupabaseHttpClientTests(unittest.TestCase):
    def test_fetch_records_paginates_complete_result_set(self) -> None:
        client = SupabaseHttpClient(
            CloudConfig("https://example.supabase.co", "sb_publishable_abcdefghijklmnopqrstuvwxyz")
        )
        rows = [
            {
                "id": f"row-{index}",
                "owner_id": "user-1",
                "entity_type": "publishers",
                "record_key": str(index),
                "payload": {"id": index},
                "version": 1,
                "deleted": False,
                "updated_at": f"2026-08-15T00:{index // 60:02d}:{index % 60:02d}Z",
                "device_id": "device",
            }
            for index in range(1200)
        ]
        ranges: list[str] = []
        paths: list[str] = []

        def fake_request(path: str, **kwargs: Any) -> list[dict[str, Any]]:
            paths.append(path)
            range_header = str((kwargs.get("headers") or {}).get("Range") or "")
            ranges.append(range_header)
            start_text, end_text = range_header.split("-", 1)
            start, end = int(start_text), int(end_text)
            return rows[start : end + 1]

        client._request = fake_request  # type: ignore[method-assign]
        result = client.fetch_records("token", "user-1")

        self.assertEqual(len(result), 1200)
        self.assertEqual(ranges, ["0-499", "500-999", "1000-1499"])
        self.assertTrue(all("order=updated_at.asc%2Cid.asc" in path for path in paths))

    def test_fetch_records_paginates_incremental_cursor_query(self) -> None:
        client = SupabaseHttpClient(
            CloudConfig("https://example.supabase.co", "sb_publishable_abcdefghijklmnopqrstuvwxyz")
        )
        paths: list[str] = []

        def fake_request(path: str, **kwargs: Any) -> list[dict[str, Any]]:
            paths.append(path)
            return []

        client._request = fake_request  # type: ignore[method-assign]
        cursor = "2026-08-15T12:34:56+00:00"
        self.assertEqual(client.fetch_records("token", "user-1", cursor), [])
        self.assertEqual(len(paths), 1)
        self.assertIn("updated_at=gte.2026-08-15T12%3A34%3A56%2B00%3A00", paths[0])



if __name__ == "__main__":
    unittest.main()
