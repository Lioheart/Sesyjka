from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
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

from .config import config_dir
from .database_manager import DatabaseManager
from .oauth import LoopbackOAuthReceiver, build_discord_authorize_url, create_pkce_pair

LOG = logging.getLogger(__name__)
DELETED_HASH = "__deleted__"
DEFAULT_SYNC_INTERVAL = 300


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
        """Mapowania są zależne od konta. Device ID pozostaje lokalny."""
        with self._lock, closing(self.connect()) as connection:
            connection.execute("DELETE FROM sync_mappings")
            connection.execute("DELETE FROM sync_conflicts")
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

    def fetch_records(self, token: str, user_id: str) -> list[dict[str, Any]]:
        query = urllib.parse.urlencode(
            {
                "select": "id,owner_id,entity_type,record_key,payload,version,deleted,updated_at,device_id",
                "owner_id": f"eq.{user_id}",
                "order": "entity_type.asc,record_key.asc",
            }
        )
        payload = self._request(f"/rest/v1/sesyjka_records?{query}", token=token)
        if payload is None:
            return []
        if not isinstance(payload, list):
            raise CloudError("Nieprawidłowa odpowiedź tabeli sesyjka_records.")
        return [dict(item) for item in payload if isinstance(item, dict)]

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
        try:
            session = self.ensure_session(url, key)
            previous_user = self.store.get_meta("last_sync_user")
            if previous_user and previous_user != session.user_id:
                # Mapowania i konflikty opisują stan jednego konta. Jeśli plik
                # sesji został podmieniony albo użytkownik zmienił konto poza GUI,
                # nie wolno zastosować mapowań poprzedniego właściciela.
                self.store.clear_account_state()
                self.store.set_meta("last_sync_at", "0")
            client = self._client(url, key)
            remote_rows = client.fetch_records(session.access_token, session.user_id)
            remote = {
                (str(row.get("entity_type")), str(row.get("record_key"))): row
                for row in remote_rows
                if row.get("entity_type") in ENTITY_BY_NAME and row.get("record_key") is not None
            }
            local = self._local_snapshot()
            report = SyncReport()

            for spec in ENTITY_SPECS:
                keys = sorted(
                    {
                        record_key
                        for entity_type, record_key in set(local) | set(remote)
                        if entity_type == spec.name
                    },
                    key=_record_key_sort_key,
                )
                # Grupy muszą trafić do systemy_rpg przed elementami należącymi do grup.
                if spec.name == "rpg_items":
                    def rpg_order(record_key: str) -> tuple[int, tuple[Any, ...]]:
                        remote_row = remote.get((spec.name, record_key)) or {}
                        payload = local.get((spec.name, record_key)) or remote_row.get("payload") or {}
                        is_group = str(payload.get("typ") or "") == "Grupa"
                        is_remote_delete = bool(remote_row.get("deleted"))
                        if is_remote_delete:
                            # Dzieci są usuwane przed grupami ze względu na self-FK.
                            phase = 3 if is_group else 2
                        else:
                            # Grupy są tworzone przed rekordami, które na nie wskazują.
                            phase = 0 if is_group else 1
                        return phase, _record_key_sort_key(record_key)
                    keys.sort(key=rpg_order)
                for record_key in keys:
                    local_payload = local.get((spec.name, record_key))
                    remote_row = remote.get((spec.name, record_key))
                    if self.store.has_open_conflict(spec.name, record_key):
                        remote_deleted = bool(remote_row.get("deleted")) if remote_row else True
                        remote_payload = dict(remote_row.get("payload") or {}) if remote_row and not remote_deleted else None
                        remote_version = int(remote_row.get("version") or 0) if remote_row else 0
                        self.store.record_conflict(
                            spec.name, record_key, local_payload, remote_payload,
                            local_payload is None, remote_deleted, remote_version,
                        )
                        report.conflicts += 1
                        continue
                    self._sync_record(client, session, spec, record_key, local_payload, remote_row, report)

            self.store.set_meta("last_sync_at", str(int(time.time())))
            self.store.set_meta("last_sync_user", session.user_id)
            return report
        finally:
            self._lock.release()

    def _sync_record(
        self,
        client: SupabaseHttpClient,
        session: CloudSession,
        spec: EntitySpec,
        record_key: str,
        local_payload: dict[str, Any] | None,
        remote_row: dict[str, Any] | None,
        report: SyncReport,
    ) -> None:
        mapping = self.store.mapping(spec.name, record_key)
        local_hash = _payload_hash(local_payload) if local_payload is not None else DELETED_HASH
        remote_deleted = bool(remote_row.get("deleted")) if remote_row else True
        remote_payload = dict(remote_row.get("payload") or {}) if remote_row and not remote_deleted else None
        remote_hash = _payload_hash(remote_payload) if remote_payload is not None else DELETED_HASH
        remote_version = int(remote_row.get("version") or 0) if remote_row else 0

        if mapping is None:
            if local_payload is not None and remote_row is None:
                pushed = self._push(client, session, spec.name, record_key, local_payload, False, 1)
                pushed_hash = _remote_hash(pushed)
                self.store.set_mapping(spec.name, record_key, local_hash, pushed_hash, int(pushed.get("version") or 1))
                report.uploaded += 1
                return
            if local_payload is None and remote_row is not None:
                if remote_deleted:
                    self.store.set_mapping(spec.name, record_key, DELETED_HASH, DELETED_HASH, remote_version)
                    report.unchanged += 1
                    return
                self._apply_remote(spec, record_key, remote_payload, deleted=False)
                self.store.set_mapping(spec.name, record_key, remote_hash, remote_hash, remote_version)
                report.downloaded += 1
                return
            if local_payload is not None and remote_row is not None:
                if not remote_deleted and local_hash == remote_hash:
                    self.store.set_mapping(spec.name, record_key, local_hash, remote_hash, remote_version)
                    report.unchanged += 1
                    return
                self.store.record_conflict(
                    spec.name, record_key, local_payload, remote_payload,
                    False, remote_deleted, remote_version,
                )
                report.conflicts += 1
                return
            return

        last_local = str(mapping["last_local_hash"] or DELETED_HASH)
        last_remote = str(mapping["last_remote_hash"] or DELETED_HASH)
        local_changed = local_hash != last_local
        remote_changed = remote_hash != last_remote

        if not local_changed and not remote_changed:
            report.unchanged += 1
            return
        if local_changed and remote_changed:
            if local_hash == remote_hash:
                self.store.set_mapping(spec.name, record_key, local_hash, remote_hash, remote_version)
                report.unchanged += 1
                return
            self.store.record_conflict(
                spec.name, record_key, local_payload, remote_payload,
                local_payload is None, remote_deleted, remote_version,
            )
            report.conflicts += 1
            return
        if local_changed:
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

        # Zmiana tylko w chmurze.
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

    def _local_snapshot(self) -> dict[tuple[str, str], dict[str, Any]]:
        result: dict[tuple[str, str], dict[str, Any]] = {}
        for spec in ENTITY_SPECS:
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

    def _apply_remote(
        self,
        spec: EntitySpec,
        record_key: str,
        payload: dict[str, Any] | None,
        *,
        deleted: bool,
    ) -> None:
        key_values = _parse_record_key(spec, record_key)
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
