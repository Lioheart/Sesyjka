from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

from sesyjka.cloud import CloudService, CloudSession, SessionTokenStore
from sesyjka.database_manager import DatabaseManager
from sesyjka.repository import Repository


class FakeSupabaseClient:
    def __init__(self) -> None:
        self.records: dict[tuple[str, str], dict[str, Any]] = {}

    def fetch_records(self, token: str, user_id: str) -> list[dict[str, Any]]:
        return [dict(row) for row in self.records.values() if row["owner_id"] == user_id]

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
            "updated_at": "2026-08-15T00:00:00Z",
            "device_id": device_id,
        }
        self.records[(entity_type, record_key)] = row
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
        }
        self.assertEqual({p.name for p in self.db.own_root.glob("*.db")} - {"sync.db"}, original)

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

    def test_conflict_is_created_when_both_sides_changed(self) -> None:
        publisher_id = self.repo.save_publisher({"nazwa": "Start", "kraj": "PL", "strona": ""})
        self.cloud.sync(self.url, self.key)
        self.repo.save_publisher({"nazwa": "Lokalna", "kraj": "PL", "strona": ""}, publisher_id)
        row = self.fake.records[("publishers", str(publisher_id))]
        row["payload"] = {**row["payload"], "nazwa": "Chmurowa"}
        row["version"] = 2
        report = self.cloud.sync(self.url, self.key)
        self.assertEqual(report.conflicts, 1)
        conflicts = self.cloud.conflicts
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].local_payload["nazwa"], "Lokalna")
        self.assertEqual(conflicts[0].remote_payload["nazwa"], "Chmurowa")

    def test_remote_conflict_resolution_updates_local_record(self) -> None:
        publisher_id = self.repo.save_publisher({"nazwa": "Start", "kraj": "PL", "strona": ""})
        self.cloud.sync(self.url, self.key)
        self.repo.save_publisher({"nazwa": "Lokalna", "kraj": "PL", "strona": ""}, publisher_id)
        row = self.fake.records[("publishers", str(publisher_id))]
        row["payload"] = {**row["payload"], "nazwa": "Chmurowa"}
        row["version"] = 2
        self.cloud.sync(self.url, self.key)
        conflict = self.cloud.conflicts[0]
        self.cloud.resolve_conflict(self.url, self.key, conflict.id, "remote")
        current = [row for row in self.repo.publishers() if int(row["id"]) == publisher_id][0]
        self.assertEqual(current["nazwa"], "Chmurowa")
        self.assertEqual(self.cloud.conflicts, [])

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

    def test_session_store_uses_owner_only_permissions(self) -> None:
        session = CloudSession("access", "refresh", 123, "uid", "u@example.com")
        self.token_store.save(session)
        mode = os.stat(self.token_store.path).st_mode & 0o777
        self.assertEqual(mode, 0o600)
        loaded = self.token_store.load()
        self.assertEqual(loaded.email, "u@example.com")
        self.token_store.clear()
        self.assertFalse(self.token_store.path.exists())


if __name__ == "__main__":
    unittest.main()
