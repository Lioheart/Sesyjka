from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from .config import DB_FILES, config_dir
from .database_manager import DatabaseManager
from .oauth import LoopbackOAuthReceiver, build_discord_authorize_url, create_pkce_pair

LOG = logging.getLogger(__name__)
DELETED_HASH = "__deleted__"
DEFAULT_SYNC_INTERVAL = 900


class CloudError(RuntimeError):
    """Błąd konfiguracji, uwierzytelnienia lub komunikacji z Sesyjka Cloud."""


class CloudOfflineError(CloudError):
    """Sieć lub usługa chmurowa jest aktualnie niedostępna."""


class CloudAuthError(CloudError):
    """Błąd Supabase Auth."""


@dataclass(frozen=True)
class CloudConfig:
    url: str
    publishable_key: str

    @classmethod
    def from_values(cls, url: str, key: str) -> "CloudConfig":
        clean_url = url.strip().rstrip("/")
        clean_key = key.strip()
        parsed = urllib.parse.urlparse(clean_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Adres Supabase musi być poprawnym adresem http:// lub https://.")
        if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("Zdalny projekt Supabase musi używać HTTPS.")
        if len(clean_key) < 20:
            raise ValueError("Klucz publishable/anon Supabase wygląda na nieprawidłowy.")
        return cls(clean_url, clean_key)


@dataclass
class CloudSession:
    access_token: str
    refresh_token: str
    expires_at: int
    user_id: str
    email: str
    provider: str = ""

    @classmethod
    def from_response(cls, payload: dict[str, Any]) -> "CloudSession | None":
        # GoTrue /auth/v1/token zwraca tokeny na najwyższym poziomie. Część
        # klientów SDK opakowuje je w pole session, więc akceptujemy obie formy.
        session = payload.get("session") if isinstance(payload.get("session"), dict) else payload
        access = str(session.get("access_token") or "")
        refresh = str(session.get("refresh_token") or "")
        if not access or not refresh:
            return None
        user = session.get("user") or payload.get("user") or {}
        user_id = str(user.get("id") or _jwt_subject(access) or "")
        email = str(user.get("email") or "")
        app_metadata = user.get("app_metadata") if isinstance(user.get("app_metadata"), dict) else {}
        provider = str(app_metadata.get("provider") or "")
        expires_at = int(session.get("expires_at") or 0)
        if not expires_at:
            expires_at = int(time.time()) + int(session.get("expires_in") or 3600)
        if not user_id:
            raise CloudAuthError("Supabase nie zwrócił identyfikatora użytkownika.")
        return cls(access, refresh, expires_at, user_id, email, provider)

    def as_json(self) -> dict[str, Any]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "user_id": self.user_id,
            "email": self.email,
            "provider": self.provider,
        }


@dataclass(frozen=True)
class EntitySpec:
    name: str
    db_file: str
    table: str
    key_columns: tuple[str, ...]
    order: int


ENTITY_SPECS: tuple[EntitySpec, ...] = (
    EntitySpec("publishers", "wydawcy.db", "wydawcy", ("id",), 10),
    EntitySpec("players", "gracze.db", "gracze", ("id",), 20),
    EntitySpec("game_systems", "systemy_rpg.db", "systemy_gry", ("id",), 30),
    EntitySpec("rpg_items", "systemy_rpg.db", "systemy_rpg", ("id",), 40),
    EntitySpec("sessions", "sesje_rpg.db", "sesje_rpg", ("id",), 50),
    EntitySpec("session_players", "sesje_rpg.db", "sesje_gracze", ("sesja_id", "gracz_id"), 60),
    EntitySpec("session_notes", "sesje_rpg.db", "sesje_notatki", ("sesja_id",), 70),
    EntitySpec("board_games", "planszowe.db", "planszowe", ("id",), 80),
    EntitySpec("digital_resources", "zasoby.db", "zasoby", ("id",), 90),
    EntitySpec("digital_locations", "zasoby.db", "lokalizacje", ("id",), 100),
)
ENTITY_BY_NAME = {spec.name: spec for spec in ENTITY_SPECS}


@dataclass
class SyncReport:
    uploaded: int = 0
    downloaded: int = 0
    deleted_local: int = 0
    deleted_remote: int = 0
    conflicts: int = 0
    unchanged: int = 0

    @property
    def changed(self) -> int:
        return self.uploaded + self.downloaded + self.deleted_local + self.deleted_remote


@dataclass
class Conflict:
    id: int
    entity_type: str
    record_key: str
    local_payload: dict[str, Any] | None
    remote_payload: dict[str, Any] | None
    local_deleted: bool
    remote_deleted: bool
    remote_version: int
    detected_at: str


class SessionTokenStore:
    """Mały magazyn sesji Supabase.

    Hasło użytkownika nigdy nie jest zapisywane. Token odświeżania musi
    przetrwać restart aplikacji, dlatego plik ma prawa 0600. W kolejnej wersji
    może zostać przeniesiony do Secret Service bez zmiany sync.db.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (config_dir() / "cloud-session.json")

    def load(self) -> CloudSession | None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return None
            return CloudSession(
                access_token=str(data.get("access_token") or ""),
                refresh_token=str(data.get("refresh_token") or ""),
                expires_at=int(data.get("expires_at") or 0),
                user_id=str(data.get("user_id") or ""),
                email=str(data.get("email") or ""),
                provider=str(data.get("provider") or ""),
            )
        except (OSError, ValueError, TypeError):
            return None

    def save(self, session: CloudSession) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(session.as_json(), ensure_ascii=False, indent=2), encoding="utf-8")
        os.chmod(temp, 0o600)
        temp.replace(self.path)
        os.chmod(self.path, 0o600)

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


class SyncStore:
    """Stan synchronizacji przechowywany wyłącznie w sync.db."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        with self._lock, closing(self.connect()) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS sync_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sync_mappings (
                    entity_type TEXT NOT NULL,
                    record_key TEXT NOT NULL,
                    last_local_hash TEXT,
                    last_remote_hash TEXT,
                    remote_version INTEGER NOT NULL DEFAULT 0,
                    last_synced_at TEXT,
                    PRIMARY KEY (entity_type, record_key)
                );
                CREATE TABLE IF NOT EXISTS sync_conflicts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_type TEXT NOT NULL,
                    record_key TEXT NOT NULL,
                    local_payload TEXT,
                    remote_payload TEXT,
                    local_deleted INTEGER NOT NULL DEFAULT 0,
                    remote_deleted INTEGER NOT NULL DEFAULT 0,
                    remote_version INTEGER NOT NULL DEFAULT 0,
                    detected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    resolved_at TEXT,
                    resolution TEXT
                );
                CREATE UNIQUE INDEX IF NOT EXISTS sync_conflicts_open_idx
                    ON sync_conflicts(entity_type, record_key)
                    WHERE resolved_at IS NULL;
                CREATE TABLE IF NOT EXISTS sync_dirty_databases (
                    db_file TEXT PRIMARY KEY,
                    changed_generation INTEGER NOT NULL
                );
                """
            )
            if self.get_meta("device_id") is None:
                self.set_meta("device_id", str(uuid.uuid4()))

    def get_meta(self, key: str) -> str | None:
        with self._lock, closing(self.connect()) as connection:
            row = connection.execute("SELECT value FROM sync_meta WHERE key=?", (key,)).fetchone()
            return str(row["value"]) if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self._lock, closing(self.connect()) as connection:
            connection.execute(
                "INSERT INTO sync_meta(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
            connection.commit()

    @property
    def device_id(self) -> str:
        return self.get_meta("device_id") or "unknown"

    def mapping(self, entity_type: str, record_key: str) -> sqlite3.Row | None:
        with self._lock, closing(self.connect()) as connection:
            return connection.execute(
                "SELECT * FROM sync_mappings WHERE entity_type=? AND record_key=?",
                (entity_type, record_key),
            ).fetchone()

    def set_mapping(
        self,
        entity_type: str,
        record_key: str,
        local_hash: str,
        remote_hash: str,
        remote_version: int,
    ) -> None:
        with self._lock, closing(self.connect()) as connection:
            connection.execute(
                """
                INSERT INTO sync_mappings
                    (entity_type, record_key, last_local_hash, last_remote_hash,
                     remote_version, last_synced_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(entity_type, record_key) DO UPDATE SET
                    last_local_hash=excluded.last_local_hash,
                    last_remote_hash=excluded.last_remote_hash,
                    remote_version=excluded.remote_version,
                    last_synced_at=CURRENT_TIMESTAMP
                """,
                (entity_type, record_key, local_hash, remote_hash, int(remote_version)),
            )
            connection.commit()

    def mapping_keys(self, entity_type: str) -> set[str]:
        with self._lock, closing(self.connect()) as connection:
            rows = connection.execute(
                "SELECT record_key FROM sync_mappings WHERE entity_type=?",
                (entity_type,),
            ).fetchall()
        return {str(row["record_key"]) for row in rows}

    def mark_dirty_database(self, db_file: str) -> None:
        if db_file not in DB_FILES:
            return
        generation = time.time_ns()
        with self._lock, closing(self.connect()) as connection:
            connection.execute(
                """
                INSERT INTO sync_dirty_databases(db_file, changed_generation)
                VALUES(?, ?)
                ON CONFLICT(db_file) DO UPDATE SET
                    changed_generation=excluded.changed_generation
                """,
                (db_file, generation),
            )
            connection.commit()

    def dirty_databases(self) -> dict[str, int]:
        with self._lock, closing(self.connect()) as connection:
            rows = connection.execute(
                "SELECT db_file, changed_generation FROM sync_dirty_databases ORDER BY db_file"
            ).fetchall()
        return {str(row["db_file"]): int(row["changed_generation"]) for row in rows}

    def clear_dirty_databases(self, snapshot: dict[str, int]) -> None:
        if not snapshot:
            return
        with self._lock, closing(self.connect()) as connection:
            for db_file, generation in snapshot.items():
                connection.execute(
                    "DELETE FROM sync_dirty_databases WHERE db_file=? AND changed_generation=?",
                    (db_file, int(generation)),
                )
            connection.commit()

    def resolve_open_conflict(self, entity_type: str, record_key: str, resolution: str = "local-auto") -> None:
        with self._lock, closing(self.connect()) as connection:
            connection.execute(
                """
                UPDATE sync_conflicts
                SET resolved_at=CURRENT_TIMESTAMP, resolution=?
                WHERE entity_type=? AND record_key=? AND resolved_at IS NULL
                """,
                (resolution, entity_type, record_key),
            )
            connection.commit()

    def has_open_conflict(self, entity_type: str, record_key: str) -> bool:
        with self._lock, closing(self.connect()) as connection:
            row = connection.execute(
                "SELECT 1 FROM sync_conflicts WHERE entity_type=? AND record_key=? AND resolved_at IS NULL",
                (entity_type, record_key),
            ).fetchone()
            return row is not None

    def record_conflict(
        self,
        entity_type: str,
        record_key: str,
        local_payload: dict[str, Any] | None,
        remote_payload: dict[str, Any] | None,
        local_deleted: bool,
        remote_deleted: bool,
        remote_version: int,
    ) -> None:
        local_json = json.dumps(local_payload, ensure_ascii=False, sort_keys=True) if local_payload is not None else None
        remote_json = json.dumps(remote_payload, ensure_ascii=False, sort_keys=True) if remote_payload is not None else None
        with self._lock, closing(self.connect()) as connection:
            existing = connection.execute(
                "SELECT id FROM sync_conflicts WHERE entity_type=? AND record_key=? AND resolved_at IS NULL",
                (entity_type, record_key),
            ).fetchone()
            if existing:
                connection.execute(
                    """
                    UPDATE sync_conflicts SET local_payload=?, remote_payload=?,
                        local_deleted=?, remote_deleted=?, remote_version=?, detected_at=CURRENT_TIMESTAMP
                    WHERE id=?
                    """,
                    (local_json, remote_json, int(local_deleted), int(remote_deleted), int(remote_version), int(existing["id"])),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO sync_conflicts
                        (entity_type, record_key, local_payload, remote_payload,
                         local_deleted, remote_deleted, remote_version)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (entity_type, record_key, local_json, remote_json, int(local_deleted), int(remote_deleted), int(remote_version)),
                )
            connection.commit()

    def conflicts(self) -> list[Conflict]:
        with self._lock, closing(self.connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM sync_conflicts WHERE resolved_at IS NULL ORDER BY detected_at, id"
            ).fetchall()
        result: list[Conflict] = []
        for row in rows:
            result.append(
                Conflict(
                    id=int(row["id"]),
                    entity_type=str(row["entity_type"]),
                    record_key=str(row["record_key"]),
                    local_payload=json.loads(row["local_payload"]) if row["local_payload"] else None,
                    remote_payload=json.loads(row["remote_payload"]) if row["remote_payload"] else None,
                    local_deleted=bool(row["local_deleted"]),
                    remote_deleted=bool(row["remote_deleted"]),
                    remote_version=int(row["remote_version"] or 0),
                    detected_at=str(row["detected_at"]),
                )
            )
        return result

    def conflict(self, conflict_id: int) -> Conflict | None:
        return next((item for item in self.conflicts() if item.id == conflict_id), None)

    def resolve_conflict_row(self, conflict_id: int, resolution: str) -> None:
        with self._lock, closing(self.connect()) as connection:
            connection.execute(
                "UPDATE sync_conflicts SET resolved_at=CURRENT_TIMESTAMP, resolution=? WHERE id=?",
                (resolution, conflict_id),
            )
            connection.commit()

    def clear_account_state(self) -> None:
        """Mapowania są zależne od konta. Device ID i lokalny dirty-set pozostają lokalne."""
        with self._lock, closing(self.connect()) as connection:
            connection.execute("DELETE FROM sync_mappings")
            connection.execute("DELETE FROM sync_conflicts")
            connection.execute(
                "DELETE FROM sync_meta WHERE key IN "
                "('last_sync_user', 'last_sync_at', 'remote_cursor_at', 'incremental_sync_ready')"
            )
            connection.commit()


class SupabaseHttpClient:
    """Minimalny klient Supabase Auth + Data REST API bez dodatkowych zależności."""

    def __init__(self, config: CloudConfig, timeout: float = 15.0) -> None:
        self.config = config
        self.timeout = timeout

    def _request(
        self,
        path: str,
        *,
        method: str = "GET",
        body: Any = None,
        token: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        url = f"{self.config.url}{path}"
        request_headers = {
            "apikey": self.config.publishable_key,
            "Accept": "application/json",
        }
        if token:
            request_headers["Authorization"] = f"Bearer {token}"
        if body is not None:
            request_headers["Content-Type"] = "application/json"
            encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
        else:
            encoded = None
        if headers:
            request_headers.update(headers)
        request = urllib.request.Request(url, data=encoded, headers=request_headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
                if not raw:
                    return None
                return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                payload = json.loads(exc.read().decode("utf-8"))
                message = payload.get("msg") or payload.get("message") or payload.get("error_description") or payload.get("error")
                error_code = str(payload.get("code") or payload.get("error_code") or "")
            except Exception:
                message = None
                error_code = ""
            if error_code == "PGRST205" or "sesyjka_records" in str(message or "") and "schema cache" in str(message or ""):
                raise CloudError(
                    "Backend Sesyjka Cloud nie został zainicjalizowany. "
                    "Tabela public.sesyjka_records nie jest dostępna w Supabase. "
                    "Administrator projektu musi wdrożyć plik supabase/schema.sql."
                ) from exc
            raise CloudError(str(message or f"Supabase HTTP {exc.code}")) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise CloudOfflineError(f"Nie można połączyć z Sesyjka Cloud: {exc}") from exc
        except (ValueError, UnicodeError) as exc:
            raise CloudError("Supabase zwrócił nieprawidłową odpowiedź JSON.") from exc

    def sign_up(self, email: str, password: str) -> tuple[CloudSession | None, dict[str, Any]]:
        payload = self._request("/auth/v1/signup", method="POST", body={"email": email, "password": password})
        if not isinstance(payload, dict):
            raise CloudAuthError("Nieprawidłowa odpowiedź rejestracji Supabase.")
        return CloudSession.from_response(payload), payload

    def sign_in(self, email: str, password: str) -> CloudSession:
        payload = self._request(
            "/auth/v1/token?grant_type=password",
            method="POST",
            body={"email": email, "password": password},
        )
        if not isinstance(payload, dict):
            raise CloudAuthError("Nieprawidłowa odpowiedź logowania Supabase.")
        session = CloudSession.from_response(payload)
        if session is None:
            raise CloudAuthError("Supabase nie zwrócił sesji użytkownika.")
        return session

    def exchange_pkce_code(self, auth_code: str, code_verifier: str) -> CloudSession:
        payload = self._request(
            "/auth/v1/token?grant_type=pkce",
            method="POST",
            body={"auth_code": auth_code, "code_verifier": code_verifier},
        )
        if not isinstance(payload, dict):
            raise CloudAuthError("Nieprawidłowa odpowiedź wymiany kodu OAuth Supabase.")
        session = CloudSession.from_response(payload)
        if session is None:
            raise CloudAuthError("Supabase nie zwrócił sesji po logowaniu Discord.")
        return session

    def refresh_session(self, refresh_token: str) -> CloudSession:
        payload = self._request(
            "/auth/v1/token?grant_type=refresh_token",
            method="POST",
            body={"refresh_token": refresh_token},
        )
        if not isinstance(payload, dict):
            raise CloudAuthError("Nieprawidłowa odpowiedź odświeżania sesji Supabase.")
        session = CloudSession.from_response(payload)
        if session is None:
            raise CloudAuthError("Nie udało się odświeżyć sesji Supabase.")
        return session

    def get_user(self, token: str) -> dict[str, Any]:
        payload = self._request("/auth/v1/user", token=token)
        if not isinstance(payload, dict):
            raise CloudAuthError("Nieprawidłowa odpowiedź danych konta Supabase.")
        return payload

    def sign_out(self, token: str) -> None:
        self._request("/auth/v1/logout", method="POST", token=token)

    def fetch_records(
        self,
        token: str,
        user_id: str,
        updated_since: str | None = None,
    ) -> list[dict[str, Any]]:
        parameters: dict[str, str] = {
            "select": "id,owner_id,entity_type,record_key,payload,version,deleted,updated_at,device_id",
            "owner_id": f"eq.{user_id}",
            "order": "updated_at.asc,id.asc",
        }
        if updated_since:
            # ``gte`` intentionally overlaps the cursor boundary. This can fetch a
            # few rows twice, but prevents losing rows that received the same
            # PostgreSQL timestamp at the edge of two synchronization passes.
            parameters["updated_at"] = f"gte.{updated_since}"
        query = urllib.parse.urlencode(parameters)
        path = f"/rest/v1/sesyjka_records?{query}"

        # PostgREST/Supabase limits result sets, so retrieve the complete delta
        # in stable pages. This matters both for the initial synchronization and
        # for a large batch of remote changes accumulated between two runs.
        page_size = 500
        offset = 0
        records: list[dict[str, Any]] = []
        while True:
            payload = self._request(
                path,
                token=token,
                headers={
                    "Range-Unit": "items",
                    "Range": f"{offset}-{offset + page_size - 1}",
                },
            )
            if payload is None:
                return records
            if not isinstance(payload, list):
                raise CloudError("Nieprawidłowa odpowiedź tabeli sesyjka_records.")
            records.extend(dict(item) for item in payload if isinstance(item, dict))
            if len(payload) < page_size:
                return records
            offset += page_size

    def fetch_record(
        self,
        token: str,
        user_id: str,
        entity_type: str,
        record_key: str,
    ) -> dict[str, Any] | None:
        query = urllib.parse.urlencode(
            {
                "select": "id,owner_id,entity_type,record_key,payload,version,deleted,updated_at,device_id",
                "owner_id": f"eq.{user_id}",
                "entity_type": f"eq.{entity_type}",
                "record_key": f"eq.{record_key}",
                "limit": "1",
            }
        )
        payload = self._request(f"/rest/v1/sesyjka_records?{query}", token=token)
        if payload is None:
            return None
        if not isinstance(payload, list):
            raise CloudError("Nieprawidłowa odpowiedź tabeli sesyjka_records.")
        for item in payload:
            if isinstance(item, dict):
                return dict(item)
        return None

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
        query = urllib.parse.urlencode({"on_conflict": "owner_id,entity_type,record_key"})
        body = {
            "owner_id": user_id,
            "entity_type": entity_type,
            "record_key": record_key,
            "payload": payload or {},
            "version": max(1, int(version)),
            "deleted": bool(deleted),
            "device_id": device_id,
        }
        response = self._request(
            f"/rest/v1/sesyjka_records?{query}",
            method="POST",
            body=body,
            token=token,
            headers={"Prefer": "resolution=merge-duplicates,return=representation"},
        )
        if isinstance(response, list) and response:
            return dict(response[0])
        if isinstance(response, dict):
            return dict(response)
        # Niektóre konfiguracje PostgREST mogą zwrócić minimalną odpowiedź.
        return {**body, "version": max(1, int(version))}


class CloudService:
    """Offline-first synchronizacja istniejących baz SQLite z Supabase."""

    def __init__(
        self,
        databases: DatabaseManager,
        *,
        token_store: SessionTokenStore | None = None,
    ) -> None:
        self.databases = databases
        self.store = SyncStore(databases.own_root / "sync.db")
        self.token_store = token_store or SessionTokenStore()
        self._session = self.token_store.load()
        self._lock = threading.Lock()
        self._active_sync_backup: Path | None = None
        self._active_sync_backup_extended = False
        self._suppress_local_tracking = 0
        self.databases.add_write_listener(self._on_local_database_write)

    def _on_local_database_write(self, db_file: str) -> None:
        if self._suppress_local_tracking:
            return
        if any(spec.db_file == db_file for spec in ENTITY_SPECS):
            self.store.mark_dirty_database(db_file)

    def _database_fingerprint(self, db_file: str) -> str:
        path = self.databases.own_root / db_file
        try:
            stat = path.stat()
        except FileNotFoundError:
            return "missing"
        return f"{stat.st_size}:{stat.st_mtime_ns}"

    def _reconcile_dirty_databases(self) -> None:
        # The write listener covers changes made by Sesyjka while it is running.
        # Fingerprints additionally detect manual/external SQLite edits performed
        # while the application was closed, without modifying domain schemas.
        for db_file in DB_FILES:
            current = self._database_fingerprint(db_file)
            previous = self.store.get_meta(f"db_fingerprint:{db_file}")
            if previous is None or previous != current:
                self.store.mark_dirty_database(db_file)

    def _store_database_fingerprints(self) -> None:
        for db_file in DB_FILES:
            self.store.set_meta(f"db_fingerprint:{db_file}", self._database_fingerprint(db_file))

    @property
    def pending_local_databases(self) -> tuple[str, ...]:
        return tuple(self.store.dirty_databases())

    @property
    def session(self) -> CloudSession | None:
        return self._session

    @property
    def signed_in(self) -> bool:
        return self._session is not None and bool(self._session.refresh_token)

    @property
    def conflicts(self) -> list[Conflict]:
        return self.store.conflicts()

    def _client(self, url: str, key: str) -> SupabaseHttpClient:
        return SupabaseHttpClient(CloudConfig.from_values(url, key))

    def sign_up(self, url: str, key: str, email: str, password: str) -> bool:
        client = self._client(url, key)
        session, _payload = client.sign_up(email.strip(), password)
        if session:
            self._session = session
            self.token_store.save(session)
            return True
        return False

    def sign_in(self, url: str, key: str, email: str, password: str) -> CloudSession:
        client = self._client(url, key)
        session = client.sign_in(email.strip(), password)
        self._session = session
        self.token_store.save(session)
        return session

    def sign_in_with_discord(
        self,
        url: str,
        key: str,
        *,
        open_browser: Callable[[str], bool] = webbrowser.open,
        timeout: float = 180.0,
    ) -> CloudSession:
        client = self._client(url, key)
        verifier, challenge = create_pkce_pair()
        try:
            receiver_context = LoopbackOAuthReceiver()
        except OSError as exc:
            raise CloudAuthError(str(exc)) from exc
        with receiver_context as receiver:
            authorize_url = build_discord_authorize_url(client.config.url, receiver.redirect_uri, challenge)
            if not bool(open_browser(authorize_url)):
                raise CloudAuthError(
                    "Nie udało się otworzyć domyślnej przeglądarki do logowania Discord."
                )
            try:
                callback = receiver.wait(timeout)
            except TimeoutError as exc:
                raise CloudAuthError(str(exc)) from exc
        if callback.error:
            raise CloudAuthError(callback.error_description or callback.error)
        if not callback.code:
            raise CloudAuthError("Discord/Supabase nie zwrócił kodu autoryzacyjnego.")
        session = client.exchange_pkce_code(callback.code, verifier)
        user = client.get_user(session.access_token)
        session.email = str(user.get("email") or session.email)
        session.user_id = str(user.get("id") or session.user_id)
        app_metadata = user.get("app_metadata") if isinstance(user.get("app_metadata"), dict) else {}
        session.provider = str(app_metadata.get("provider") or "discord")
        self._session = session
        self.token_store.save(session)
        return session

    def sign_out(self, url: str, key: str) -> None:
        session = self._session
        if session:
            try:
                self._client(url, key).sign_out(session.access_token)
            except CloudError:
                LOG.warning("Wylogowanie zdalne nie powiodło się; usuwam sesję lokalną", exc_info=True)
        self._session = None
        self.token_store.clear()
        self.store.clear_account_state()

    def ensure_session(self, url: str, key: str) -> CloudSession:
        session = self._session
        if session is None:
            raise CloudAuthError("Zaloguj się do Sesyjka Cloud.")
        if session.expires_at > int(time.time()) + 90:
            return session
        refreshed = self._client(url, key).refresh_session(session.refresh_token)
        # Czasem odświeżenie nie zwraca emaila. Zachowujemy go z poprzedniej sesji.
        if not refreshed.email:
            refreshed.email = session.email
        if not refreshed.provider:
            refreshed.provider = session.provider
        self._session = refreshed
        self.token_store.save(refreshed)
        return refreshed

    def validate_session(self, url: str, key: str) -> CloudSession:
        session = self.ensure_session(url, key)
        user = self._client(url, key).get_user(session.access_token)
        session.email = str(user.get("email") or session.email)
        session.user_id = str(user.get("id") or session.user_id)
        app_metadata = user.get("app_metadata") if isinstance(user.get("app_metadata"), dict) else {}
        session.provider = str(app_metadata.get("provider") or session.provider)
        self.token_store.save(session)
        return session

    def sync(self, url: str, key: str) -> SyncReport:
        if self.databases.guest_mode:
            raise CloudError("Synchronizacja jest wyłączona w trybie gościa.")
        if not self._lock.acquire(blocking=False):
            raise CloudError("Synchronizacja już trwa.")

        safety_backup: Path | None = None
        try:
            safety_backup = self.databases.create_safety_backup("cloud-sync", ("sync.db",))
            self._active_sync_backup = safety_backup
            self._active_sync_backup_extended = False

            session = self.ensure_session(url, key)
            previous_user = self.store.get_meta("last_sync_user")
            account_changed = bool(previous_user and previous_user != session.user_id)
            if account_changed:
                # Mapping state belongs to exactly one cloud account. Local data
                # remains authoritative and is reconciled afresh with the new
                # account on the next pass.
                self.store.clear_account_state()

            self._reconcile_dirty_databases()
            full_sync = (
                account_changed
                or self.store.get_meta("incremental_sync_ready") != "1"
                or self.store.get_meta("last_sync_user") != session.user_id
            )
            dirty_snapshot = self.store.dirty_databases()
            dirty_files = set(dirty_snapshot)

            client = self._client(url, key)
            remote_cursor = None if full_sync else self.store.get_meta("remote_cursor_at")
            remote_rows = client.fetch_records(
                session.access_token,
                session.user_id,
                updated_since=remote_cursor,
            )
            remote_complete = full_sync or not remote_cursor
            remote = {
                (str(row.get("entity_type")), str(row.get("record_key"))): row
                for row in remote_rows
                if row.get("entity_type") in ENTITY_BY_NAME and row.get("record_key") is not None
            }

            if full_sync:
                local = self._local_snapshot()
            else:
                # Only databases that were actually changed locally are scanned.
                # Remote delta rows are read individually when their database was
                # otherwise untouched. No full local snapshot is needed.
                local = self._local_snapshot(dirty_files)
                for entity_key in remote:
                    if entity_key in local:
                        continue
                    entity_type, record_key = entity_key
                    spec = ENTITY_BY_NAME[entity_type]
                    local[entity_key] = self._local_record(spec, record_key)

            report = SyncReport()

            for spec in ENTITY_SPECS:
                if full_sync:
                    keys = {
                        record_key
                        for entity_type, record_key in set(local) | set(remote)
                        if entity_type == spec.name
                    }
                else:
                    keys = {
                        record_key
                        for entity_type, record_key in remote
                        if entity_type == spec.name
                    }
                    if spec.db_file in dirty_files:
                        keys.update(
                            record_key
                            for entity_type, record_key in local
                            if entity_type == spec.name
                        )
                        # Mapped records absent from the current table represent
                        # local deletions and must be emitted as tombstones.
                        keys.update(self.store.mapping_keys(spec.name))

                ordered_keys = sorted(keys, key=_record_key_sort_key)
                if spec.name == "rpg_items":
                    key_set = set(ordered_keys)
                    depth_cache: dict[str, int] = {}

                    def rpg_payload(record_key: str) -> dict[str, Any]:
                        remote_row = remote.get((spec.name, record_key)) or {}
                        if remote_row and not bool(remote_row.get("deleted")):
                            payload = remote_row.get("payload")
                            if isinstance(payload, dict):
                                return payload
                        payload = local.get((spec.name, record_key))
                        return payload if isinstance(payload, dict) else {}

                    def rpg_depth(record_key: str, visiting: set[str] | None = None) -> int:
                        cached = depth_cache.get(record_key)
                        if cached is not None:
                            return cached
                        visiting = set(visiting or ())
                        if record_key in visiting:
                            return 0
                        visiting.add(record_key)
                        payload = rpg_payload(record_key)
                        parent = payload.get("system_glowny_id")
                        parent_key = str(parent) if parent is not None else ""
                        if parent_key and parent_key in key_set:
                            value = 1 + rpg_depth(parent_key, visiting)
                        else:
                            value = 0
                        depth_cache[record_key] = value
                        return value

                    def rpg_order(record_key: str) -> tuple[int, int, tuple[Any, ...]]:
                        remote_row = remote.get((spec.name, record_key)) or {}
                        remote_delete = bool(remote_row.get("deleted"))
                        depth = rpg_depth(record_key)
                        return (
                            1 if remote_delete else 0,
                            -depth if remote_delete else depth,
                            _record_key_sort_key(record_key),
                        )

                    ordered_keys.sort(key=rpg_order)

                for record_key in ordered_keys:
                    entity_key = (spec.name, record_key)
                    if entity_key not in local:
                        local[entity_key] = self._local_record(spec, record_key)
                    local_payload = local.get(entity_key)
                    remote_row = remote.get(entity_key)
                    had_conflict = self.store.has_open_conflict(spec.name, record_key)
                    self._sync_record(
                        client,
                        session,
                        spec,
                        record_key,
                        local_payload,
                        remote_row,
                        report,
                        remote_complete=remote_complete,
                    )
                    if had_conflict:
                        # 0.9.11 uses deterministic local-first conflict handling.
                        # Old unresolved conflicts are closed once the local value
                        # has been reconciled successfully.
                        self.store.resolve_open_conflict(spec.name, record_key)

            # Advance the remote cursor only to rows that were actually fetched.
            # We intentionally do not advance it from our own uploads because a
            # different device may have written between the fetch and the push.
            # Keeping the older cursor makes the next pass re-read that overlap
            # instead of risking a missed remote update.
            fetched_timestamps = [
                str(row.get("updated_at") or "")
                for row in remote_rows
                if str(row.get("updated_at") or "")
            ]
            if fetched_timestamps:
                self.store.set_meta("remote_cursor_at", max(fetched_timestamps))

            self.store.set_meta("last_sync_at", str(int(time.time())))
            self.store.set_meta("last_sync_user", session.user_id)
            self.store.set_meta("incremental_sync_ready", "1")
            self._store_database_fingerprints()
            self.store.clear_dirty_databases(dirty_snapshot)

            if self._active_sync_backup_extended and safety_backup is not None:
                self.databases.prune_safety_backups("cloud-sync", keep=10)
            elif safety_backup is not None:
                shutil.rmtree(safety_backup, ignore_errors=True)
            return report
        except Exception as exc:
            if safety_backup is not None and safety_backup.exists():
                domain_changes_started = self._active_sync_backup_extended
                try:
                    self.databases.restore_safety_backup(safety_backup)
                except Exception as restore_exc:
                    raise CloudError(
                        "Synchronizacja została przerwana, a automatyczne przywrócenie kopii "
                        f"bezpieczeństwa nie powiodło się. Kopia: {safety_backup}. "
                        f"Błąd synchronizacji: {exc}. Błąd przywracania: {restore_exc}"
                    ) from exc
                if not domain_changes_started:
                    shutil.rmtree(safety_backup, ignore_errors=True)
                    raise
                message = (
                    "Synchronizacja została przerwana. Lokalne bazy przywrócono do stanu "
                    f"sprzed synchronizacji z kopii {safety_backup.name}. Przyczyna: {exc}"
                )
                if isinstance(exc, CloudOfflineError):
                    raise CloudOfflineError(message) from exc
                raise CloudError(message) from exc
            raise
        finally:
            self._active_sync_backup = None
            self._active_sync_backup_extended = False
            self._lock.release()

    def _ensure_sync_domain_backup(self) -> None:
        backup = self._active_sync_backup
        if backup is None or self._active_sync_backup_extended:
            return
        self.databases.extend_safety_backup(backup, DB_FILES)
        self._active_sync_backup_extended = True

    def _sync_record(
        self,
        client: SupabaseHttpClient,
        session: CloudSession,
        spec: EntitySpec,
        record_key: str,
        local_payload: dict[str, Any] | None,
        remote_row: dict[str, Any] | None,
        report: SyncReport,
        *,
        remote_complete: bool = True,
    ) -> None:
        mapping = self.store.mapping(spec.name, record_key)
        local_hash = _payload_hash(local_payload) if local_payload is not None else DELETED_HASH

        # During an incremental pass, absence from ``remote_rows`` means "not
        # changed since the remote cursor", not "missing in the cloud". If the
        # record already has a mapping, we can decide from the local hash alone.
        if remote_row is None and not remote_complete:
            if mapping is None:
                remote_row = client.fetch_record(
                    session.access_token, session.user_id, spec.name, record_key
                )
                return self._sync_record(
                    client, session, spec, record_key, local_payload, remote_row, report,
                    remote_complete=True,
                )
            last_local = str(mapping["last_local_hash"] or DELETED_HASH)
            if local_hash == last_local:
                report.unchanged += 1
                return
            version = int(mapping["remote_version"] or 0) + 1
            pushed = self._push(
                client,
                session,
                spec.name,
                record_key,
                local_payload,
                local_payload is None,
                version,
            )
            pushed_hash = _remote_hash(pushed)
            pushed_version = int(pushed.get("version") or version)
            self.store.set_mapping(spec.name, record_key, local_hash, pushed_hash, pushed_version)
            if local_payload is None:
                report.deleted_remote += 1
            else:
                report.uploaded += 1
            return

        # In a complete remote snapshot, a missing row is genuinely absent.
        # Sesyjka uses explicit tombstones for deletions, so a physically missing
        # remote row never causes deletion of local data. Local state is restored
        # to the cloud instead.
        if remote_row is None:
            if local_payload is None:
                if mapping is not None:
                    self.store.set_mapping(spec.name, record_key, DELETED_HASH, DELETED_HASH, 0)
                report.unchanged += 1
                return
            version = max(1, int(mapping["remote_version"] or 0) + 1) if mapping is not None else 1
            pushed = self._push(
                client, session, spec.name, record_key, local_payload, False, version
            )
            pushed_hash = _remote_hash(pushed)
            self.store.set_mapping(
                spec.name, record_key, local_hash, pushed_hash, int(pushed.get("version") or version)
            )
            report.uploaded += 1
            return

        remote_deleted = bool(remote_row.get("deleted"))
        remote_payload = dict(remote_row.get("payload") or {}) if not remote_deleted else None
        remote_hash = _payload_hash(remote_payload) if remote_payload is not None else DELETED_HASH
        remote_version = int(remote_row.get("version") or 0)

        if mapping is None:
            if local_payload is None:
                # Re-check immediately before a cloud-only insert. A local row may
                # have been created after the incremental snapshot was taken. In
                # that race the newly committed SQLite value still has priority.
                current_local = self._local_record(spec, record_key)
                if current_local is not None:
                    return self._sync_record(
                        client, session, spec, record_key, current_local, remote_row, report,
                        remote_complete=True,
                    )
                if remote_deleted:
                    self.store.set_mapping(spec.name, record_key, DELETED_HASH, DELETED_HASH, remote_version)
                    report.unchanged += 1
                    return
                self._apply_remote(spec, record_key, remote_payload, deleted=False)
                self.store.set_mapping(spec.name, record_key, remote_hash, remote_hash, remote_version)
                report.downloaded += 1
                return
            if not remote_deleted and local_hash == remote_hash:
                self.store.set_mapping(spec.name, record_key, local_hash, remote_hash, remote_version)
                report.unchanged += 1
                return

            # Local-first policy: when the same key exists independently on both
            # sides, the local SQLite row is authoritative. This also resurrects
            # a remotely deleted record when it still exists locally.
            pushed = self._push(
                client,
                session,
                spec.name,
                record_key,
                local_payload,
                False,
                max(1, remote_version + 1),
            )
            pushed_hash = _remote_hash(pushed)
            pushed_version = int(pushed.get("version") or max(1, remote_version + 1))
            self.store.set_mapping(spec.name, record_key, local_hash, pushed_hash, pushed_version)
            report.uploaded += 1
            return

        last_local = str(mapping["last_local_hash"] or DELETED_HASH)
        last_remote = str(mapping["last_remote_hash"] or DELETED_HASH)
        local_changed = local_hash != last_local
        remote_changed = remote_hash != last_remote

        if not local_changed and not remote_changed:
            report.unchanged += 1
            return
        if local_changed:
            # Local database has priority. If both sides changed, the local row
            # wins deterministically instead of generating a blocking conflict.
            pushed = self._push(
                client,
                session,
                spec.name,
                record_key,
                local_payload,
                local_payload is None,
                max(remote_version, int(mapping["remote_version"] or 0)) + 1,
            )
            pushed_hash = _remote_hash(pushed)
            version = int(pushed.get("version") or remote_version + 1)
            self.store.set_mapping(spec.name, record_key, local_hash, pushed_hash, version)
            if local_payload is None:
                report.deleted_remote += 1
            else:
                report.uploaded += 1
            return

        # Only the cloud changed according to the snapshot. Re-read SQLite just
        # before applying the remote value so an edit committed while this sync
        # was running cannot be overwritten by an older snapshot decision.
        current_local = self._local_record(spec, record_key)
        current_hash = _payload_hash(current_local) if current_local is not None else DELETED_HASH
        if current_hash != local_hash:
            return self._sync_record(
                client, session, spec, record_key, current_local, remote_row, report,
                remote_complete=True,
            )
        self._apply_remote(spec, record_key, remote_payload, deleted=remote_deleted)
        self.store.set_mapping(spec.name, record_key, remote_hash, remote_hash, remote_version)
        if remote_deleted:
            report.deleted_local += 1
        else:
            report.downloaded += 1

    def _push(
        self,
        client: SupabaseHttpClient,
        session: CloudSession,
        entity_type: str,
        record_key: str,
        payload: dict[str, Any] | None,
        deleted: bool,
        version: int,
    ) -> dict[str, Any]:
        return client.upsert_record(
            session.access_token,
            session.user_id,
            entity_type=entity_type,
            record_key=record_key,
            payload=payload,
            deleted=deleted,
            version=version,
            device_id=self.store.device_id,
        )

    def _local_snapshot(
        self,
        db_files: set[str] | None = None,
    ) -> dict[tuple[str, str], dict[str, Any]]:
        result: dict[tuple[str, str], dict[str, Any]] = {}
        for spec in ENTITY_SPECS:
            if db_files is not None and spec.db_file not in db_files:
                continue
            try:
                with self.databases.connect(spec.db_file) as connection:
                    rows = connection.execute(f"SELECT * FROM {spec.table}").fetchall()
            except FileNotFoundError:
                continue
            for row in rows:
                payload = {key: row[key] for key in row.keys()}
                record_key = _record_key(spec, payload)
                result[(spec.name, record_key)] = payload
        return result

    def _local_record(self, spec: EntitySpec, record_key: str) -> dict[str, Any] | None:
        key_values = _parse_record_key(spec, record_key)
        where = " AND ".join(f"{column}=?" for column in spec.key_columns)
        try:
            with self.databases.connect(spec.db_file) as connection:
                row = connection.execute(
                    f"SELECT * FROM {spec.table} WHERE {where}", key_values
                ).fetchone()
        except FileNotFoundError:
            return None
        if row is None:
            return None
        return {key: row[key] for key in row.keys()}

    def _apply_remote(
        self,
        spec: EntitySpec,
        record_key: str,
        payload: dict[str, Any] | None,
        *,
        deleted: bool,
    ) -> None:
        key_values = _parse_record_key(spec, record_key)
        self._ensure_sync_domain_backup()
        try:
            self._suppress_local_tracking += 1
            try:
                with self.databases.connect(spec.db_file, write=True) as connection:
                    if deleted:
                        where = " AND ".join(f"{column}=?" for column in spec.key_columns)
                        connection.execute(f"DELETE FROM {spec.table} WHERE {where}", key_values)
                        return
                    if payload is None:
                        raise CloudError("Brak danych rekordu chmurowego.")
                    columns = {str(row[1]) for row in connection.execute(f"PRAGMA table_info({spec.table})")}
                    clean = {key: value for key, value in payload.items() if key in columns}
                    for column, value in zip(spec.key_columns, key_values):
                        clean[column] = value

                    # Od 0.9.17 rekord Grupa jest wyłącznie kontenerem
                    # organizacyjnym. Stary klient lub stary rekord w chmurze nie
                    # może ponownie wprowadzić usuniętych metadanych do lokalnej
                    # bazy SQLite.
                    if (
                        spec.name == "rpg_items"
                        and str(clean.get("typ") or "").strip().casefold() == "grupa"
                    ):
                        clean.update(
                            {
                                "system_glowny_id": None,
                                "typ_suplementu": None,
                                "wydawca_id": None,
                                "fizyczny": 0,
                                "pdf": 0,
                                "jezyk": None,
                                "status_gra": None,
                                "status_kolekcja": None,
                                "cena_zakupu": None,
                                "waluta_zakupu": None,
                                "cena_sprzedazy": None,
                                "waluta_sprzedazy": None,
                                "vtt": None,
                                "system_glowny_nazwa_custom": None,
                                "cena_fiz": None,
                                "cena_pdf": None,
                                "cena_vtt": None,
                                "rok_wydania": None,
                                "isbn": None,
                            }
                        )
                    names = list(clean)
                    placeholders = ", ".join("?" for _ in names)
                    conflict = ", ".join(spec.key_columns)
                    updates = ", ".join(f"{name}=excluded.{name}" for name in names if name not in spec.key_columns)
                    if updates:
                        sql = (
                            f"INSERT INTO {spec.table} ({', '.join(names)}) VALUES ({placeholders}) "
                            f"ON CONFLICT({conflict}) DO UPDATE SET {updates}"
                        )
                    else:
                        sql = f"INSERT OR IGNORE INTO {spec.table} ({', '.join(names)}) VALUES ({placeholders})"
                    connection.execute(sql, tuple(clean[name] for name in names))
            finally:
                self._suppress_local_tracking -= 1
        except sqlite3.IntegrityError as exc:
            raise CloudError(
                f"Nie można zastosować rekordu {spec.name}/{record_key} z chmury: {exc}"
            ) from exc

    def resolve_conflict(self, url: str, key: str, conflict_id: int, resolution: str) -> None:
        conflict = self.store.conflict(conflict_id)
        if conflict is None:
            raise CloudError("Konflikt nie istnieje lub został już rozwiązany.")
        spec = ENTITY_BY_NAME.get(conflict.entity_type)
        if spec is None:
            raise CloudError("Nieznany typ rekordu konfliktu.")
        session = self.ensure_session(url, key)
        if resolution == "remote":
            self._apply_remote(spec, conflict.record_key, conflict.remote_payload, deleted=conflict.remote_deleted)
            remote_hash = DELETED_HASH if conflict.remote_deleted else _payload_hash(conflict.remote_payload)
            self.store.set_mapping(conflict.entity_type, conflict.record_key, remote_hash, remote_hash, conflict.remote_version)
            self.store.resolve_conflict_row(conflict_id, "remote")
            return
        if resolution != "local":
            raise ValueError("Nieznany sposób rozwiązania konfliktu.")
        local_payload = self._local_snapshot().get((conflict.entity_type, conflict.record_key))
        client = self._client(url, key)
        pushed = self._push(
            client,
            session,
            conflict.entity_type,
            conflict.record_key,
            local_payload,
            local_payload is None,
            max(1, conflict.remote_version + 1),
        )
        local_hash = DELETED_HASH if local_payload is None else _payload_hash(local_payload)
        remote_hash = _remote_hash(pushed)
        self.store.set_mapping(
            conflict.entity_type,
            conflict.record_key,
            local_hash,
            remote_hash,
            int(pushed.get("version") or conflict.remote_version + 1),
        )
        self.store.resolve_conflict_row(conflict_id, "local")


def _payload_hash(payload: dict[str, Any] | None) -> str:
    if payload is None:
        return DELETED_HASH
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _remote_hash(row: dict[str, Any]) -> str:
    if bool(row.get("deleted")):
        return DELETED_HASH
    payload = row.get("payload")
    return _payload_hash(dict(payload) if isinstance(payload, dict) else {})


def _record_key(spec: EntitySpec, payload: dict[str, Any]) -> str:
    return "|".join(str(payload[column]) for column in spec.key_columns)


def _parse_record_key(spec: EntitySpec, record_key: str) -> tuple[Any, ...]:
    parts = record_key.split("|")
    if len(parts) != len(spec.key_columns):
        raise CloudError(f"Nieprawidłowy klucz rekordu {spec.name}: {record_key}")
    values: list[Any] = []
    for part in parts:
        try:
            values.append(int(part))
        except ValueError:
            values.append(part)
    return tuple(values)


def _record_key_sort_key(record_key: str) -> tuple[Any, ...]:
    result: list[Any] = []
    for part in record_key.split("|"):
        try:
            result.append((0, int(part)))
        except ValueError:
            result.append((1, part))
    return tuple(result)


def _jwt_subject(token: str) -> str | None:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        raw = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(raw.encode("ascii")).decode("utf-8"))
        return str(payload.get("sub") or "") or None
    except Exception:
        return None
