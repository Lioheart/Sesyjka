from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from .config import config_dir

DTRPG_API_BASE = "https://api.drivethrurpg.com/api"
DTRPG_API_VERSION = "vBeta"
DTRPG_ACCOUNT_URL = "https://www.drivethrurpg.com/account.php"
DTRPG_LIBRARY_URL = "https://www.drivethrurpg.com/en/mylibrary"
DTRPG_USER_AGENT = "Sesyjka/0.9.13 (+https://github.com/Lioheart/Sesyjka)"


class DigitalResourceError(RuntimeError):
    pass


class DriveThruRPGError(DigitalResourceError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        detail: str = "",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class ScanResult:
    path: Path
    relative_path: str
    filename: str
    size: int
    sha256: str
    suggested_rpg_id: int | None = None
    confidence: float = 0.0


@dataclass(frozen=True)
class DriveThruLibraryItem:
    external_id: str
    order_product_id: int
    product_id: int | None
    file_index: int | None
    title: str
    filename: str
    size: int | None
    sha256: str
    isbn: str
    publisher: str
    product_url: str
    resource_type: str
    format_name: str
    date_purchased: str
    product_title: str = ""
    file_title: str = ""


def normalize_text(value: str) -> str:
    text = str(value or "").casefold()
    text = re.sub(r"\.[a-z0-9]{2,5}$", "", text)
    text = re.sub(r"[_\-.]+", " ", text)
    text = re.sub(r"[^0-9a-ząćęłńóśźż ]+", " ", text)
    return " ".join(text.split())


def _tokens(value: str) -> set[str]:
    return {token for token in normalize_text(value).split() if len(token) > 1}


def match_rpg_item(filename: str, candidates: Sequence[dict[str, Any]]) -> tuple[int | None, float]:
    """Dopasuj nazwę pliku do pozycji RPG bez zgadywania przy niskiej pewności."""
    normalized_file = normalize_text(Path(filename).stem)
    file_tokens = _tokens(filename)
    if not normalized_file:
        return None, 0.0

    best_id: int | None = None
    best_score = 0.0
    second_score = 0.0
    for candidate in candidates:
        if str(candidate.get("typ") or "").casefold() == "grupa":
            continue
        title = str(candidate.get("nazwa") or "")
        normalized_title = normalize_text(title)
        if not normalized_title:
            continue
        title_tokens = _tokens(title)
        if normalized_file == normalized_title:
            score = 1.0
        elif normalized_title in normalized_file:
            score = min(0.98, 0.88 + min(len(normalized_title), 50) / 500)
        elif normalized_file in normalized_title and len(normalized_file) >= 8:
            score = 0.9
        else:
            union = file_tokens | title_tokens
            overlap = file_tokens & title_tokens
            score = (len(overlap) / len(union)) if union else 0.0
            if title_tokens and title_tokens.issubset(file_tokens):
                score = max(score, 0.9)
        if score > best_score:
            second_score = best_score
            best_score = score
            best_id = int(candidate["id"])
        elif score > second_score:
            second_score = score

    # Automatyczne przypisanie wyłącznie przy wysokiej pewności i wyraźnej przewadze.
    if best_score >= 0.90 and best_score - second_score >= 0.08:
        return best_id, best_score
    return None, best_score


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while True:
            chunk = stream.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def scan_pdf_directory(
    root: Path,
    candidates: Sequence[dict[str, Any]],
    *,
    recursive: bool = True,
) -> list[ScanResult]:
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("Wybrany katalog nie istnieje.")
    iterator: Iterable[Path] = root.rglob("*") if recursive else root.glob("*")
    result: list[ScanResult] = []
    for path in iterator:
        if not path.is_file() or path.suffix.casefold() != ".pdf":
            continue
        record_id, confidence = match_rpg_item(path.name, candidates)
        result.append(
            ScanResult(
                path=path,
                relative_path=path.relative_to(root).as_posix(),
                filename=path.name,
                size=path.stat().st_size,
                sha256=sha256_file(path),
                suggested_rpg_id=record_id,
                confidence=confidence,
            )
        )
    result.sort(key=lambda item: item.relative_path.casefold())
    return result


class DriveThruKeyStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (config_dir() / "drivethrurpg.json")

    def load(self) -> str:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return str(payload.get("application_key") or "").strip() if isinstance(payload, dict) else ""
        except (OSError, ValueError, TypeError):
            return ""

    def save(self, application_key: str) -> None:
        key = str(application_key or "").strip()
        if not key:
            self.clear()
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps({"application_key": key}, indent=2), encoding="utf-8")
        os.chmod(temp, 0o600)
        temp.replace(self.path)
        os.chmod(self.path, 0o600)

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


class DriveThruRPGClient:
    """Klient odczytu biblioteki DriveThruRPG przez Application Key.

    DriveThruRPG nie publikuje stabilnej dokumentacji konsumenckiego API.
    Bieżąca specyfikacja reverse-engineered opisuje ``order_products`` jako
    paginowany JSON:API z polami ``links``/``meta``/``data``/``included``.
    Klient zachowuje także obsługę bezpośredniej listy produktów jako fallback
    zgodnościowy dla wcześniejszych wariantów backendu.
    """

    def __init__(self, application_key: str, timeout: float = 25.0) -> None:
        self.application_key = str(application_key or "").strip()
        self.timeout = timeout
        if not self.application_key:
            raise ValueError("Podaj Application Key DriveThruRPG.")

    def _request_json(
        self,
        url: str,
        *,
        method: str = "GET",
        token: str = "",
        body: bytes | None = None,
        bearer: bool = False,
    ) -> Any:
        headers = {
            "User-Agent": DTRPG_USER_AGENT,
            "Accept": "application/json",
            # urllib nie rozpakowuje automatycznie gzip/deflate. Prosimy o
            # odpowiedź nieskompresowaną, ale niżej i tak obsługujemy kompresję,
            # ponieważ CDN DriveThruRPG może zwrócić ją niezależnie od tego nagłówka.
            "Accept-Encoding": "identity",
        }
        if token:
            # Bieżący oficjalny SDK DriveThruRPG wysyła surowy JWT bez prefiksu
            # ``Bearer``. Specyfikacja OpenAPI nadal opisuje Bearer, dlatego
            # ``library()`` ma jednokrotny fallback kompatybilnościowy.
            headers["Authorization"] = f"Bearer {token}" if bearer else token
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = response.read()
                content_encoding = str(response.headers.get("Content-Encoding") or "").casefold()
                content_type = str(response.headers.get("Content-Type") or "").casefold()
                payload = self._decode_content_encoding(payload, content_encoding)
        except urllib.error.HTTPError as exc:
            error_payload = exc.read()
            content_encoding = str(exc.headers.get("Content-Encoding") or "").casefold() if exc.headers else ""
            try:
                error_payload = self._decode_content_encoding(error_payload, content_encoding)
            except DriveThruRPGError:
                pass
            detail = error_payload.decode("utf-8", "replace")[:1000]
            is_auth_key_request = "/auth_key" in urllib.parse.urlsplit(url).path
            if is_auth_key_request and exc.code in {401, 403}:
                raise DriveThruRPGError(
                    "DriveThruRPG odrzucił Application Key. Sprawdź, czy klucz jest "
                    "aktualny i czy ma włączone My Library Access. "
                    f"HTTP {exc.code}. {detail}".strip(),
                    status_code=exc.code,
                    detail=detail,
                ) from exc
            if token and exc.code == 401:
                raise DriveThruRPGError(
                    "DriveThruRPG odrzucił token sesji JWT uzyskany z poprawnie "
                    "wywołanego endpointu auth_key. To nie oznacza automatycznie, "
                    "że Application Key jest błędny. "
                    f"HTTP 401. {detail}".strip(),
                    status_code=exc.code,
                    detail=detail,
                ) from exc
            if token and exc.code == 403:
                raise DriveThruRPGError(
                    "DriveThruRPG odmówił dostępu do biblioteki dla bieżącej sesji. "
                    "Sprawdź, czy Application Key ma włączone My Library Access. "
                    f"HTTP 403. {detail}".strip(),
                    status_code=exc.code,
                    detail=detail,
                ) from exc
            raise DriveThruRPGError(
                f"DriveThruRPG zwrócił HTTP {exc.code}. {detail}".strip(),
                status_code=exc.code,
                detail=detail,
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise DriveThruRPGError(f"Nie można połączyć z DriveThruRPG: {exc}") from exc
        try:
            return json.loads(payload.decode("utf-8-sig"))
        except (UnicodeDecodeError, ValueError) as exc:
            preview = payload.decode("utf-8", "replace")[:240].strip()
            extra = f" Początek odpowiedzi: {preview}" if preview else ""
            type_info = f" Content-Type: {content_type}." if content_type else ""
            raise DriveThruRPGError(
                "DriveThruRPG zwrócił odpowiedź, która nie jest JSON-em." + type_info + extra
            ) from exc


    @staticmethod
    def _decode_content_encoding(payload: bytes, content_encoding: str = "") -> bytes:
        """Rozpakuj odpowiedź HTTP z API DriveThruRPG.

        Biblioteczny backend DriveThruRPG bywa obsługiwany przez warstwę CDN,
        która zwraca gzip/deflate. ``urllib.request`` nie wykonuje dekompresji
        automatycznie, więc bez tego poprawny JSON zaczynał się w Sesyjce od
        binarnych bajtów nagłówka gzip i był błędnie raportowany jako nie-JSON.
        """
        if not payload:
            return payload
        encoding = str(content_encoding or "").split(",", 1)[0].strip().casefold()
        try:
            if encoding in {"gzip", "x-gzip"} or payload.startswith(b"\x1f\x8b"):
                return gzip.decompress(payload)
            if encoding == "deflate":
                try:
                    return zlib.decompress(payload)
                except zlib.error:
                    return zlib.decompress(payload, -zlib.MAX_WBITS)
        except (OSError, EOFError, zlib.error) as exc:
            raise DriveThruRPGError(
                f"DriveThruRPG zwrócił uszkodzoną skompresowaną odpowiedź ({encoding or 'gzip'})."
            ) from exc
        return payload

    def authenticate(self) -> str:
        query = urllib.parse.urlencode({"applicationKey": self.application_key})
        url = f"{DTRPG_API_BASE}/{DTRPG_API_VERSION}/auth_key?{query}"
        # Aktualny SDK wysyła pusty obiekt JSON. Sam POST bez body nie jest
        # równoważny na wszystkich warstwach proxy/CDN.
        payload = self._request_json(url, method="POST", body=b"{}")
        if not isinstance(payload, dict):
            raise DriveThruRPGError(
                "DriveThruRPG zwrócił nieoczekiwany format odpowiedzi podczas uwierzytelniania."
            )
        token = str(payload.get("token") or "").strip()
        if not token:
            state = payload.get("state") or payload.get("message") or payload.get("error") or ""
            raise DriveThruRPGError(
                "Nie udało się uwierzytelnić Application Key. "
                "Sprawdź klucz i włącz My Library Access w ustawieniach DriveThruRPG. "
                + str(state)
            )
        return token

    def _request_library_page(self, url: str, token: str) -> Any:
        """Pobierz stronę biblioteki z kompatybilnością wariantów Authorization.

        Bieżący Python SDK DriveThruRPG używa surowego JWT jako wartości
        ``Authorization``. Część opisu OpenAPI nadal wskazuje schemat Bearer.
        Najpierw używamy zachowania SDK. Jeżeli serwer odpowie 401, wykonujemy
        dokładnie jedną próbę zgodną ze starszą interpretacją OpenAPI.
        """
        try:
            return self._request_json(url, token=token)
        except DriveThruRPGError as raw_error:
            if raw_error.status_code != 401:
                raise

        try:
            return self._request_json(url, token=token, bearer=True)
        except DriveThruRPGError as bearer_error:
            if bearer_error.status_code == 401:
                raise DriveThruRPGError(
                    "DriveThruRPG odrzucił token JWT zarówno w formacie używanym przez "
                    "bieżący SDK, jak i z prefiksem Bearer. Application Key został "
                    "wcześniej wymieniony na token, więc błąd dotyczy sesji lub sposobu "
                    "autoryzacji biblioteki. "
                    f"HTTP 401. {bearer_error.detail}".strip(),
                    status_code=401,
                    detail=bearer_error.detail,
                ) from bearer_error
            raise

    @staticmethod
    def _safe_int(value: Any) -> int | None:
        try:
            parsed = int(str(value).strip())
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    @staticmethod
    def _relation_id(item: dict[str, Any], name: str) -> str:
        relationships = item.get("relationships") if isinstance(item.get("relationships"), dict) else {}
        relation = relationships.get(name) if isinstance(relationships.get(name), dict) else {}
        data = relation.get("data") if isinstance(relation.get("data"), dict) else {}
        return str(data.get("id") or "")

    @staticmethod
    def _included_map(payload: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
        result: dict[tuple[str, str], dict[str, Any]] = {}
        for item in payload.get("included") or []:
            if not isinstance(item, dict):
                continue
            resource_type = str(item.get("type") or "")
            resource_id = str(item.get("id") or "")
            if resource_type and resource_id:
                result[(resource_type.casefold(), resource_id)] = item
        return result

    @staticmethod
    def _included_by_id(
        included: dict[tuple[str, str], dict[str, Any]], resource_id: str
    ) -> dict[str, Any]:
        for (_kind, candidate_id), item in included.items():
            if candidate_id == resource_id:
                return item
        return {}

    @staticmethod
    def _included_publisher_name(payload: dict[str, Any], publisher_id: int | None) -> str:
        if not publisher_id:
            return ""
        for item in payload.get("included") or []:
            if not isinstance(item, dict) or str(item.get("type") or "").casefold() != "publisher":
                continue
            attrs = item.get("attributes") if isinstance(item.get("attributes"), dict) else {}
            try:
                candidate_id = int(attrs.get("publisherId"))
            except (TypeError, ValueError):
                candidate_id = None
            if candidate_id == publisher_id:
                return str(attrs.get("name") or "").strip()
        return ""

    @staticmethod
    def _resource_type(filename: str) -> tuple[str, str]:
        suffix = Path(filename).suffix.casefold().lstrip(".")
        if suffix == "pdf":
            return "PDF", "PDF"
        if suffix in {"mod", "fvtt", "zip", "dd2vtt", "uvtt"}:
            return "VTT", suffix.upper() or "VTT"
        if suffix:
            return "Inne", suffix.upper()
        return "WWW", "Online"

    @staticmethod
    def _checksum(file_info: dict[str, Any]) -> str:
        checksums = file_info.get("checksums") or []
        if isinstance(checksums, list):
            for checksum in checksums:
                if isinstance(checksum, dict) and checksum.get("checksum"):
                    value = str(checksum["checksum"]).strip()
                    if re.fullmatch(r"[0-9a-fA-F]{64}", value):
                        return value.lower()
        return ""

    def _make_item(
        self,
        *,
        order_product_id: int,
        product_id: int | None,
        file_index: int | None,
        title: str,
        publisher: str,
        filename: str = "",
        size: int | None = None,
        sha256: str = "",
        isbn: str = "",
        date_purchased: str = "",
        product_title: str = "",
        file_title: str = "",
    ) -> DriveThruLibraryItem:
        resource_type, format_name = self._resource_type(filename) if filename else ("WWW", "DriveThruRPG")
        product_url = (
            f"https://www.drivethrurpg.com/en/product/{product_id}"
            if product_id
            else DTRPG_LIBRARY_URL
        )
        suffix = str(file_index) if file_index is not None else "product"
        return DriveThruLibraryItem(
            external_id=f"dtrpg:{order_product_id}:{suffix}",
            order_product_id=order_product_id,
            product_id=product_id,
            file_index=file_index,
            title=title or filename or f"DriveThruRPG #{order_product_id}",
            filename=filename,
            size=size,
            sha256=sha256,
            isbn=isbn,
            publisher=publisher,
            product_url=product_url,
            resource_type=resource_type,
            format_name=format_name,
            date_purchased=date_purchased,
            product_title=product_title or title,
            file_title=file_title,
        )

    @staticmethod
    def _file_display_title(file_info: dict[str, Any], filename: str, product_title: str) -> str:
        """Zwróć przyjazny tytuł pliku do pokazania obok nazwy produktu.

        DriveThruRPG może podawać przy pliku etykietę niezależną od
        technicznej nazwy pliku. Jeżeli jej nie ma, używamy nazwy pliku bez
        rozszerzenia. Nazwa produktu pozostaje ostatecznym fallbackiem.
        """
        for key in ("title", "name", "displayName", "label"):
            value = str(file_info.get(key) or "").strip()
            if value:
                return value
        stem = Path(filename).stem.strip()
        if stem:
            stem = re.sub(r"_+", " ", stem)
            return " ".join(stem.split())
        return product_title

    def _parse_current_product_list(self, payload: list[Any]) -> list[DriveThruLibraryItem]:
        """Parsuj bieżący format ``order_products`` używany przez Library App.

        Element ma postać zbliżoną do::

            {"productId": "123", "publisher": {"name": "..."},
             "name": "Tytuł", "orderProductId": 456,
             "fileLastModified": "...", "files": [...]}
        """
        result: list[DriveThruLibraryItem] = []
        for product in payload:
            if not isinstance(product, dict):
                continue
            order_product_id = self._safe_int(product.get("orderProductId"))
            if not order_product_id:
                continue
            product_id = self._safe_int(product.get("productId"))
            title = str(product.get("name") or "").strip()
            publisher_data = product.get("publisher")
            publisher = (
                str(publisher_data.get("name") or "").strip()
                if isinstance(publisher_data, dict)
                else str(publisher_data or "").strip()
            )
            isbn = re.sub(r"[^0-9Xx]", "", str(product.get("isbn") or ""))
            # Bieżący format podaje fileLastModified, ale nie jest to data zakupu.
            date_purchased = str(product.get("datePurchased") or "")
            files = product.get("files") if isinstance(product.get("files"), list) else []
            if not files:
                result.append(
                    self._make_item(
                        order_product_id=order_product_id,
                        product_id=product_id,
                        file_index=None,
                        title=title,
                        publisher=publisher,
                        isbn=isbn,
                        date_purchased=date_purchased,
                        product_title=title,
                    )
                )
                continue
            for position, file_info in enumerate(files):
                if not isinstance(file_info, dict):
                    continue
                try:
                    index = int(file_info.get("index"))
                except (TypeError, ValueError):
                    index = position
                filename = str(file_info.get("filename") or file_info.get("title") or "").strip()
                size = self._safe_int(file_info.get("size"))
                file_title = self._file_display_title(file_info, filename, title)
                result.append(
                    self._make_item(
                        order_product_id=order_product_id,
                        product_id=product_id,
                        file_index=index,
                        title=title,
                        publisher=publisher,
                        filename=filename,
                        size=size,
                        sha256=self._checksum(file_info),
                        isbn=isbn,
                        date_purchased=date_purchased,
                        product_title=title,
                        file_title=file_title,
                    )
                )
        return result

    def _parse_jsonapi_page(self, payload: dict[str, Any]) -> list[DriveThruLibraryItem]:
        """Parsuj paginowany format JSON:API zwracany przez ``order_products``."""
        included = self._included_map(payload)
        result: list[DriveThruLibraryItem] = []
        for item in payload.get("data") or []:
            if not isinstance(item, dict):
                continue
            attrs = item.get("attributes") if isinstance(item.get("attributes"), dict) else {}
            order_product_id = self._safe_int(attrs.get("orderProductId") or item.get("id"))
            if not order_product_id:
                continue
            product_id = self._safe_int(attrs.get("productId"))
            product_rel_id = self._relation_id(item, "product")
            publisher_rel_id = self._relation_id(item, "publisher")
            product_inc = self._included_by_id(included, product_rel_id) if product_rel_id else {}
            publisher_inc = self._included_by_id(included, publisher_rel_id) if publisher_rel_id else {}
            product_attrs = product_inc.get("attributes") if isinstance(product_inc.get("attributes"), dict) else {}
            publisher_attrs = publisher_inc.get("attributes") if isinstance(publisher_inc.get("attributes"), dict) else {}
            if not product_id:
                product_id = self._safe_int(product_attrs.get("productId") or product_rel_id)
            description = product_attrs.get("description") if isinstance(product_attrs.get("description"), dict) else {}
            title = str(attrs.get("name") or description.get("name") or product_attrs.get("name") or "").strip()
            publisher_id = self._safe_int(attrs.get("royaltyPublisherId"))
            publisher = (
                str(
                    (attrs.get("publisher") or {}).get("name")
                    if isinstance(attrs.get("publisher"), dict)
                    else ""
                ).strip()
                or str(publisher_attrs.get("name") or "").strip()
                or self._included_publisher_name(payload, publisher_id)
            )
            isbn = re.sub(r"[^0-9Xx]", "", str(attrs.get("isbn") or ""))
            files = attrs.get("files") if isinstance(attrs.get("files"), list) else []
            if not files:
                result.append(
                    self._make_item(
                        order_product_id=order_product_id,
                        product_id=product_id,
                        file_index=None,
                        title=title,
                        publisher=publisher,
                        size=self._safe_int(attrs.get("filesize")),
                        isbn=isbn,
                        date_purchased=str(attrs.get("datePurchased") or ""),
                        product_title=title,
                    )
                )
                continue
            for position, file_info in enumerate(files):
                if not isinstance(file_info, dict):
                    continue
                try:
                    index = int(file_info.get("index"))
                except (TypeError, ValueError):
                    index = position
                filename = str(file_info.get("filename") or file_info.get("title") or "").strip()
                file_title = self._file_display_title(file_info, filename, title)
                result.append(
                    self._make_item(
                        order_product_id=order_product_id,
                        product_id=product_id,
                        file_index=index,
                        title=title,
                        publisher=publisher,
                        filename=filename,
                        size=self._safe_int(file_info.get("size")),
                        sha256=self._checksum(file_info),
                        isbn=isbn,
                        date_purchased=str(attrs.get("datePurchased") or ""),
                        product_title=title,
                        file_title=file_title,
                    )
                )
        return result

    def _parse_page(self, payload: Any) -> list[DriveThruLibraryItem]:
        if isinstance(payload, list):
            return self._parse_current_product_list(payload)
        if isinstance(payload, dict) and isinstance(payload.get("data"), list):
            return self._parse_jsonapi_page(payload)
        raise DriveThruRPGError(
            "DriveThruRPG zwrócił nieobsługiwany format biblioteki. "
            "API DriveThruRPG jest nieudokumentowane i mogło zostać ponownie zmienione."
        )

    def library(self, page_size: int = 50) -> list[DriveThruLibraryItem]:
        token = self.authenticate()
        # Bieżący endpoint biblioteki jest limitowany do 50 produktów na stronę.
        per_page = max(1, min(int(page_size or 50), 50))
        page = 1
        all_items: list[DriveThruLibraryItem] = []
        seen_external_ids: set[str] = set()
        seen_page_signatures: set[tuple[str, ...]] = set()

        while page <= 1000:
            query = urllib.parse.urlencode(
                {
                    "getChecksum": 1,
                    "getFilters": 0,
                    "page": page,
                    "pageSize": per_page,
                    "library": "true",
                    "archived": 0,
                }
            )
            url = f"{DTRPG_API_BASE}/{DTRPG_API_VERSION}/order_products?{query}"
            payload = self._request_library_page(url, token)
            parsed = self._parse_page(payload)

            if isinstance(payload, list) and not payload:
                break

            signature = tuple(item.external_id for item in parsed)
            if signature and signature in seen_page_signatures:
                break
            if signature:
                seen_page_signatures.add(signature)

            for item in parsed:
                if item.external_id in seen_external_ids:
                    continue
                seen_external_ids.add(item.external_id)
                all_items.append(item)

            # Paginowany format JSON:API podaje jawny link ``next``. Bez niego
            # kończymy. Bezpośrednia lista pozostaje tylko kompatybilnościowym fallbackiem.
            if isinstance(payload, dict):
                links = payload.get("links") if isinstance(payload.get("links"), dict) else {}
                if not str(links.get("next") or "").strip():
                    break

            page += 1

        return all_items
