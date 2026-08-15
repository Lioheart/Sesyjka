from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from .config import cache_dir

USER_AGENT = "Sesyjka/0.8.7 (+https://github.com/Lioheart/Sesyjka)"
OPEN_LIBRARY_SEARCH = "https://openlibrary.org/search.json"
OPEN_LIBRARY_COVERS = "https://covers.openlibrary.org/b"
GOOGLE_BOOKS_SEARCH = "https://www.googleapis.com/books/v1/volumes"
MAX_COVER_BYTES = 8 * 1024 * 1024
ALLOWED_COVER_HOSTS = {"covers.openlibrary.org", "books.google.com", "books.googleusercontent.com"}


@dataclass(slots=True)
class BookLookupResult:
    isbn: str
    title: str = ""
    published_year: str = ""
    cover_url: str = ""
    price_amount: float | None = None
    price_currency: str = ""
    price_kind: str = ""
    price_source: str = ""
    metadata_sources: tuple[str, ...] = ()

    def has_metadata(self) -> bool:
        return bool(self.title or self.published_year or self.cover_url)

    def has_price(self) -> bool:
        return self.price_amount is not None and self.price_amount > 0 and bool(self.price_currency)


def normalize_isbn(value: str) -> str:
    return re.sub(r"[^0-9Xx]", "", str(value or "")).upper()


def _year(value: Any) -> str:
    if value is None:
        return ""
    match = re.search(r"(?:18|19|20|21)\d{2}", str(value))
    return match.group(0) if match else ""


def _json_get(url: str, *, timeout: float) -> dict[str, Any] | None:
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except (HTTPError, URLError, TimeoutError, OSError):
        return None
    try:
        parsed = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _open_library_result(isbn: str, *, timeout: float) -> BookLookupResult | None:
    fields = ",".join(
        (
            "title",
            "first_publish_year",
            "cover_i",
            "editions",
            "editions.title",
            "editions.publish_date",
            "editions.cover_i",
            "editions.isbn",
        )
    )
    query = urlencode({"q": f"isbn:{isbn}", "fields": fields, "limit": 1})
    data = _json_get(f"{OPEN_LIBRARY_SEARCH}?{query}", timeout=timeout)
    if not data:
        return None
    docs = data.get("docs")
    if not isinstance(docs, list) or not docs or not isinstance(docs[0], dict):
        return None
    doc = docs[0]

    title = str(doc.get("title") or "").strip()
    published_year = _year(doc.get("first_publish_year"))
    cover_id = doc.get("cover_i")

    editions = doc.get("editions")
    if isinstance(editions, dict):
        edition_docs = editions.get("docs")
        if isinstance(edition_docs, list) and edition_docs and isinstance(edition_docs[0], dict):
            edition = edition_docs[0]
            edition_title = str(edition.get("title") or "").strip()
            if edition_title:
                title = edition_title
            edition_year = _year(edition.get("publish_date"))
            if edition_year:
                published_year = edition_year
            if edition.get("cover_i"):
                cover_id = edition.get("cover_i")

    cover_url = (
        f"{OPEN_LIBRARY_COVERS}/id/{cover_id}-L.jpg?default=false"
        if cover_id
        else ""
    )

    return BookLookupResult(
        isbn=isbn,
        title=title,
        published_year=published_year,
        cover_url=cover_url,
        metadata_sources=("Open Library",),
    )


def _google_books_result(isbn: str, *, timeout: float) -> BookLookupResult | None:
    params: dict[str, Any] = {
        "q": f"isbn:{isbn}",
        "maxResults": 1,
        "projection": "full",
    }
    api_key = os.environ.get("SESYJKA_GOOGLE_BOOKS_API_KEY", "").strip()
    if api_key:
        params["key"] = api_key
    data = _json_get(f"{GOOGLE_BOOKS_SEARCH}?{urlencode(params)}", timeout=timeout)
    if not data:
        return None
    items = data.get("items")
    if not isinstance(items, list) or not items or not isinstance(items[0], dict):
        return None
    item = items[0]
    volume = item.get("volumeInfo") if isinstance(item.get("volumeInfo"), dict) else {}
    sale = item.get("saleInfo") if isinstance(item.get("saleInfo"), dict) else {}

    title = str(volume.get("title") or "").strip()
    published_year = _year(volume.get("publishedDate"))
    cover_url = ""
    image_links = volume.get("imageLinks")
    if isinstance(image_links, dict):
        for key in ("extraLarge", "large", "medium", "small", "thumbnail", "smallThumbnail"):
            candidate = str(image_links.get(key) or "").strip()
            if candidate:
                cover_url = candidate.replace("http://", "https://", 1)
                break

    price_amount: float | None = None
    price_currency = ""
    for price_key in ("retailPrice", "listPrice"):
        price = sale.get(price_key)
        if not isinstance(price, dict):
            continue
        try:
            amount = float(price.get("amount"))
        except (TypeError, ValueError):
            continue
        currency_code = str(price.get("currencyCode") or "").strip().upper()
        if amount > 0 and currency_code:
            price_amount = amount
            price_currency = currency_code
            break

    is_ebook = bool(sale.get("isEbook"))
    price_kind = "e-book" if is_ebook else "wydanie w Google Books"
    return BookLookupResult(
        isbn=isbn,
        title=title,
        published_year=published_year,
        cover_url=cover_url,
        price_amount=price_amount,
        price_currency=price_currency,
        price_kind=price_kind,
        price_source="Google Books" if price_amount is not None else "",
        metadata_sources=("Google Books",),
    )


def _merge(primary: BookLookupResult | None, secondary: BookLookupResult | None, isbn: str) -> BookLookupResult:
    if primary is None and secondary is None:
        return BookLookupResult(
            isbn=isbn,
            cover_url=f"{OPEN_LIBRARY_COVERS}/isbn/{isbn}-L.jpg?default=false",
        )
    if primary is None:
        assert secondary is not None
        return secondary
    if secondary is None:
        return primary

    sources = tuple(dict.fromkeys((*primary.metadata_sources, *secondary.metadata_sources)))
    return BookLookupResult(
        isbn=isbn,
        title=primary.title or secondary.title,
        published_year=primary.published_year or secondary.published_year,
        cover_url=primary.cover_url or secondary.cover_url,
        price_amount=secondary.price_amount if secondary.price_amount is not None else primary.price_amount,
        price_currency=secondary.price_currency or primary.price_currency,
        price_kind=secondary.price_kind or primary.price_kind,
        price_source=secondary.price_source or primary.price_source,
        metadata_sources=sources,
    )


def lookup_book(isbn_value: str, *, timeout: float = 8.0) -> BookLookupResult:
    """Pobiera jednorazowo metadane wydania na podstawie ISBN.

    Open Library jest podstawowym źródłem tytułu, roku i okładki. Google Books
    uzupełnia brakujące metadane i, gdy usługa zwróci ``saleInfo``, dostarcza
    informacyjną cenę online. Brak sieci lub odpowiedzi dostawcy nie jest błędem
    krytycznym dla aplikacji i skutkuje częściowym/pustym wynikiem.
    """

    isbn = normalize_isbn(isbn_value)
    if not isbn:
        return BookLookupResult(isbn="")
    open_library = _open_library_result(isbn, timeout=timeout)
    google_books = _google_books_result(isbn, timeout=timeout)
    result = _merge(open_library, google_books, isbn)
    if not result.cover_url:
        result.cover_url = f"{OPEN_LIBRARY_COVERS}/isbn/{isbn}-L.jpg?default=false"
    return result


def cover_cache_path(isbn_value: str) -> Path:
    isbn = normalize_isbn(isbn_value) or "unknown"
    folder = cache_dir() / "covers"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{isbn}.jpg"


def download_cover(result: BookLookupResult, *, timeout: float = 8.0) -> Path | None:
    if not result.cover_url:
        return None
    parsed_url = urlparse(result.cover_url)
    if parsed_url.scheme != "https" or (parsed_url.hostname or "").lower() not in ALLOWED_COVER_HOSTS:
        return None
    target = cover_cache_path(result.isbn)
    if target.is_file() and target.stat().st_size > 0:
        return target

    request = Request(
        result.cover_url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "image/*",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            content_type = str(response.headers.get("Content-Type") or "").lower()
            if content_type and not content_type.startswith("image/"):
                return None
            payload = response.read(MAX_COVER_BYTES + 1)
    except (HTTPError, URLError, TimeoutError, OSError):
        return None
    if not payload or len(payload) > MAX_COVER_BYTES:
        return None
    if not (payload.startswith(b"\xff\xd8\xff") or payload.startswith(b"\x89PNG\r\n\x1a\n")):
        return None

    temporary = target.with_suffix(".tmp")
    try:
        temporary.write_bytes(payload)
        temporary.replace(target)
    except OSError:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        return None
    return target
