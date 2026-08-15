from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from .config import cache_dir

USER_AGENT = "Sesyjka/0.8.8 (+https://github.com/Lioheart/Sesyjka)"
BN_SEARCH = "https://data.bn.org.pl/api/institutions/bibs.json"
BN_NETWORK_SEARCH = "https://data.bn.org.pl/api/networks/bibs.json"
OPEN_LIBRARY_SEARCH = "https://openlibrary.org/search.json"
OPEN_LIBRARY_COVERS = "https://covers.openlibrary.org/b"
GOOGLE_BOOKS_SEARCH = "https://www.googleapis.com/books/v1/volumes"
GOOGLE_BOOKS_CONTENT = "https://books.google.com/books/content"
MAX_COVER_BYTES = 8 * 1024 * 1024
ALLOWED_COVER_HOSTS = {
    "covers.openlibrary.org",
    "books.google.com",
    "books.googleusercontent.com",
}


@dataclass(slots=True)
class BookLookupResult:
    isbn: str
    title: str = ""
    published_year: str = ""
    publisher: str = ""
    cover_url: str = ""
    cover_candidates: tuple[str, ...] = ()
    price_amount: float | None = None
    price_currency: str = ""
    price_kind: str = ""
    price_source: str = ""
    metadata_sources: tuple[str, ...] = ()

    def has_metadata(self) -> bool:
        return bool(self.title or self.published_year or self.publisher or self.cover_url or self.cover_candidates)

    def has_price(self) -> bool:
        return self.price_amount is not None and self.price_amount > 0 and bool(self.price_currency)

    def covers(self) -> tuple[str, ...]:
        return _unique_urls((self.cover_url, *self.cover_candidates))


def normalize_isbn(value: str) -> str:
    """Normalizuje ISBN, usuwając myślniki, spacje i inne separatory."""
    return re.sub(r"[^0-9Xx]", "", str(value or "")).upper()


def isbn10_to_isbn13(value: str) -> str:
    isbn10 = normalize_isbn(value)
    if len(isbn10) != 10 or not isbn10[:9].isdigit() or not (isbn10[-1].isdigit() or isbn10[-1] == "X"):
        return ""
    core = "978" + isbn10[:9]
    total = sum((1 if index % 2 == 0 else 3) * int(digit) for index, digit in enumerate(core))
    return core + str((10 - total % 10) % 10)


def isbn13_to_isbn10(value: str) -> str:
    isbn13 = normalize_isbn(value)
    if len(isbn13) != 13 or not isbn13.isdigit() or not isbn13.startswith("978"):
        return ""
    core = isbn13[3:12]
    total = sum((10 - index) * int(digit) for index, digit in enumerate(core))
    check = (11 - total % 11) % 11
    if check == 10:
        check_char = "X"
    else:
        check_char = str(check)
    return core + check_char


def isbn_variants(value: str) -> tuple[str, ...]:
    normalized = normalize_isbn(value)
    values = [normalized] if normalized else []
    if len(normalized) == 10:
        converted = isbn10_to_isbn13(normalized)
    elif len(normalized) == 13:
        converted = isbn13_to_isbn10(normalized)
    else:
        converted = ""
    if converted and converted not in values:
        values.append(converted)
    return tuple(values)


def _year(value: Any) -> str:
    if value is None:
        return ""
    match = re.search(r"(?:18|19|20|21)\d{2}", str(value))
    return match.group(0) if match else ""


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple)):
        for item in value:
            result = _text(item)
            if result:
                return result
        return ""
    if isinstance(value, dict):
        for key in ("name", "value", "label", "text"):
            result = _text(value.get(key))
            if result:
                return result
        return ""
    return str(value).strip()


def _unique_urls(values: Iterable[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        url = str(value or "").strip()
        if not url:
            continue
        if url.startswith("http://"):
            url = "https://" + url[7:]
        if url not in seen:
            seen.add(url)
            result.append(url)
    return tuple(result)


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


def _candidate_records(data: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("bibs", "docs", "items", "results", "records"):
        value = data.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    # Niektóre API zwracają rekord bez opakowującej listy.
    if any(key in data for key in ("title", "publisher", "publicationYear", "isbnIssn")):
        return [data]
    return []


def _record_isbns(record: dict[str, Any]) -> set[str]:
    raw_values: list[Any] = []
    for key in ("isbnIssn", "isbn", "ISBN", "industryIdentifiers"):
        value = record.get(key)
        if isinstance(value, list):
            raw_values.extend(value)
        elif value is not None:
            raw_values.append(value)
    result: set[str] = set()
    for raw in raw_values:
        if isinstance(raw, dict):
            raw = raw.get("identifier") or raw.get("value") or ""
        # W polach bibliotecznych może znajdować się tekst obok ISBN.
        for token in re.findall(r"(?:97[89][0-9\-\s]{10,20}|[0-9Xx][0-9Xx\-\s]{8,18})", str(raw)):
            normalized = normalize_isbn(token)
            if len(normalized) in (10, 13):
                result.add(normalized)
    return result


def _bn_result(isbn: str, *, timeout: float) -> BookLookupResult | None:
    """Pobiera rekord z publicznego API Biblioteki Narodowej.

    BN jest szczególnie wartościowym źródłem dla polskich wydań. Wyszukiwanie
    wykonywane jest po znormalizowanym ISBN bez myślników, ale próbujemy także
    odpowiadającego mu ISBN-10/ISBN-13.
    """

    variants = isbn_variants(isbn)
    for endpoint, source_name in (
        (BN_SEARCH, "Biblioteka Narodowa"),
        (BN_NETWORK_SEARCH, "Biblioteka Narodowa - połączone katalogi"),
    ):
        for identifier in variants:
            query = urlencode({"isbnIssn": identifier, "limit": 10})
            data = _json_get(f"{endpoint}?{query}", timeout=timeout)
            if not data:
                continue
            records = _candidate_records(data)
            if not records:
                continue

            wanted = set(variants)
            matching = [record for record in records if not _record_isbns(record) or _record_isbns(record) & wanted]
            record = matching[0] if matching else records[0]
            title = _text(record.get("title"))
            publisher = _text(record.get("publisher"))
            published_year = _year(record.get("publicationYear") or record.get("publishDate") or record.get("date"))
            if title or publisher or published_year:
                return BookLookupResult(
                    isbn=normalize_isbn(isbn),
                    title=title,
                    publisher=publisher,
                    published_year=published_year,
                    metadata_sources=(source_name,),
                )
    return None


def _open_library_result(isbn: str, *, timeout: float) -> BookLookupResult | None:
    fields = ",".join(
        (
            "title",
            "first_publish_year",
            "publisher",
            "cover_i",
            "editions",
            "editions.title",
            "editions.publish_date",
            "editions.publisher",
            "editions.cover_i",
            "editions.isbn",
        )
    )
    wanted = set(isbn_variants(isbn))
    for identifier in isbn_variants(isbn):
        query = urlencode({"q": f"isbn:{identifier}", "fields": fields, "limit": 5})
        data = _json_get(f"{OPEN_LIBRARY_SEARCH}?{query}", timeout=timeout)
        if not data:
            continue
        docs = data.get("docs")
        if not isinstance(docs, list) or not docs:
            continue

        doc = next((item for item in docs if isinstance(item, dict)), None)
        if not isinstance(doc, dict):
            continue
        title = _text(doc.get("title"))
        publisher = _text(doc.get("publisher"))
        published_year = _year(doc.get("first_publish_year"))
        cover_id = doc.get("cover_i")

        editions = doc.get("editions")
        if isinstance(editions, dict):
            edition_docs = editions.get("docs")
            if isinstance(edition_docs, list):
                valid_editions = [item for item in edition_docs if isinstance(item, dict)]
                matching_editions = []
                for edition in valid_editions:
                    edition_isbns = {
                        normalize_isbn(value)
                        for value in (edition.get("isbn") or [])
                        if normalize_isbn(value)
                    }
                    if edition_isbns & wanted:
                        matching_editions.append(edition)
                edition = matching_editions[0] if matching_editions else (valid_editions[0] if valid_editions else None)
                if isinstance(edition, dict):
                    title = _text(edition.get("title")) or title
                    publisher = _text(edition.get("publisher")) or publisher
                    published_year = _year(edition.get("publish_date")) or published_year
                    cover_id = edition.get("cover_i") or cover_id

        candidates: list[str] = []
        if cover_id:
            candidates.append(f"{OPEN_LIBRARY_COVERS}/id/{cover_id}-L.jpg?default=false")
        for identifier_candidate in isbn_variants(isbn):
            candidates.append(f"{OPEN_LIBRARY_COVERS}/isbn/{identifier_candidate}-L.jpg?default=false")

        return BookLookupResult(
            isbn=normalize_isbn(isbn),
            title=title,
            published_year=published_year,
            publisher=publisher,
            cover_url=candidates[0] if candidates else "",
            cover_candidates=tuple(candidates[1:]),
            metadata_sources=("Open Library",),
        )
    return None


def _google_query_data(query_text: str, *, timeout: float) -> dict[str, Any] | None:
    params: dict[str, Any] = {
        "q": query_text,
        "maxResults": 10,
        "projection": "full",
    }
    api_key = os.environ.get("SESYJKA_GOOGLE_BOOKS_API_KEY", "").strip()
    if api_key:
        params["key"] = api_key
    return _json_get(f"{GOOGLE_BOOKS_SEARCH}?{urlencode(params)}", timeout=timeout)


def _google_item_isbns(item: dict[str, Any]) -> set[str]:
    volume = item.get("volumeInfo") if isinstance(item.get("volumeInfo"), dict) else {}
    identifiers = volume.get("industryIdentifiers")
    result: set[str] = set()
    if isinstance(identifiers, list):
        for entry in identifiers:
            if not isinstance(entry, dict):
                continue
            value = normalize_isbn(entry.get("identifier") or "")
            if value:
                result.add(value)
    return result


def _normalized_words(value: str) -> set[str]:
    return {word for word in re.findall(r"\w+", str(value or "").casefold()) if len(word) > 1}


def _score_google_item(item: dict[str, Any], *, wanted_isbns: set[str], title_hint: str, publisher_hint: str) -> int:
    score = 0
    item_isbns = _google_item_isbns(item)
    if item_isbns & wanted_isbns:
        score += 100
    volume = item.get("volumeInfo") if isinstance(item.get("volumeInfo"), dict) else {}
    title = _text(volume.get("title"))
    publisher = _text(volume.get("publisher"))
    title_words = _normalized_words(title_hint)
    item_title_words = _normalized_words(title)
    if title_words:
        intersection = len(title_words & item_title_words)
        score += intersection * 8
        if title.casefold() == title_hint.casefold():
            score += 30
    if publisher_hint and publisher:
        if publisher.casefold() == publisher_hint.casefold():
            score += 20
        elif publisher_hint.casefold() in publisher.casefold() or publisher.casefold() in publisher_hint.casefold():
            score += 10
    if isinstance(volume.get("imageLinks"), dict):
        score += 2
    return score


def _google_cover_candidates(item: dict[str, Any]) -> tuple[str, ...]:
    volume = item.get("volumeInfo") if isinstance(item.get("volumeInfo"), dict) else {}
    candidates: list[str] = []
    image_links = volume.get("imageLinks")
    if isinstance(image_links, dict):
        for key in ("extraLarge", "large", "medium", "small", "thumbnail", "smallThumbnail"):
            candidate = _text(image_links.get(key))
            if candidate:
                candidates.append(candidate)
    volume_id = _text(item.get("id"))
    if volume_id:
        # Google często potrafi wyrenderować front cover po ID woluminu nawet,
        # gdy pole imageLinks jest nieobecne w odpowiedzi wyszukiwania.
        candidates.extend(
            (
                f"{GOOGLE_BOOKS_CONTENT}?id={volume_id}&printsec=frontcover&img=1&zoom=3&source=gbs_api",
                f"{GOOGLE_BOOKS_CONTENT}?id={volume_id}&printsec=frontcover&img=1&zoom=2&source=gbs_api",
            )
        )
    return _unique_urls(candidates)


def _google_result_from_item(item: dict[str, Any], isbn: str) -> BookLookupResult:
    volume = item.get("volumeInfo") if isinstance(item.get("volumeInfo"), dict) else {}
    sale = item.get("saleInfo") if isinstance(item.get("saleInfo"), dict) else {}
    covers = _google_cover_candidates(item)

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
        currency_code = _text(price.get("currencyCode")).upper()
        if amount > 0 and currency_code:
            price_amount = amount
            price_currency = currency_code
            break

    is_ebook = bool(sale.get("isEbook"))
    return BookLookupResult(
        isbn=normalize_isbn(isbn),
        title=_text(volume.get("title")),
        published_year=_year(volume.get("publishedDate")),
        publisher=_text(volume.get("publisher")),
        cover_url=covers[0] if covers else "",
        cover_candidates=tuple(covers[1:]),
        price_amount=price_amount,
        price_currency=price_currency,
        price_kind="e-book" if is_ebook else "wydanie w Google Books",
        price_source="Google Books" if price_amount is not None else "",
        metadata_sources=("Google Books",),
    )


def _google_books_result(
    isbn: str,
    *,
    timeout: float,
    title_hint: str = "",
    publisher_hint: str = "",
) -> BookLookupResult | None:
    variants = isbn_variants(isbn)
    queries: list[str] = []
    for identifier in variants:
        queries.extend((f"isbn:{identifier}", identifier))
    if title_hint:
        escaped_title = title_hint.replace('"', " ").strip()
        if publisher_hint:
            escaped_publisher = publisher_hint.replace('"', " ").strip()
            queries.append(f'intitle:"{escaped_title}" inpublisher:"{escaped_publisher}"')
        queries.append(f'intitle:"{escaped_title}"')
        queries.append(f'"{escaped_title}"')

    wanted = set(variants)
    best_item: dict[str, Any] | None = None
    best_score = -1
    seen_queries: set[str] = set()
    for query_text in queries:
        if not query_text or query_text in seen_queries:
            continue
        seen_queries.add(query_text)
        data = _google_query_data(query_text, timeout=timeout)
        if not data:
            continue
        items = data.get("items")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            score = _score_google_item(
                item,
                wanted_isbns=wanted,
                title_hint=title_hint,
                publisher_hint=publisher_hint,
            )
            if score > best_score:
                best_item = item
                best_score = score
        # Trafienie po identyfikatorze jest wystarczająco pewne. Nie wykonuj
        # kolejnych zapytań tylko dla lepszego wyniku tekstowego.
        if best_score >= 100:
            break

    if best_item is None:
        return None
    # Bez zgodnego ISBN wymagamy co najmniej sensownego dopasowania tytułu.
    if best_score < 8 and title_hint:
        return None
    return _google_result_from_item(best_item, isbn)


def _merge_many(results: Iterable[BookLookupResult | None], isbn: str) -> BookLookupResult:
    valid = [result for result in results if result is not None]
    if not valid:
        fallback_covers = tuple(
            f"{OPEN_LIBRARY_COVERS}/isbn/{candidate}-L.jpg?default=false"
            for candidate in isbn_variants(isbn)
        )
        return BookLookupResult(
            isbn=normalize_isbn(isbn),
            cover_url=fallback_covers[0] if fallback_covers else "",
            cover_candidates=tuple(fallback_covers[1:]),
        )

    title = next((result.title for result in valid if result.title), "")
    year = next((result.published_year for result in valid if result.published_year), "")
    publisher = next((result.publisher for result in valid if result.publisher), "")
    covers = _unique_urls(url for result in valid for url in result.covers())
    priced = next((result for result in valid if result.has_price()), None)
    sources = tuple(dict.fromkeys(source for result in valid for source in result.metadata_sources))
    return BookLookupResult(
        isbn=normalize_isbn(isbn),
        title=title,
        published_year=year,
        publisher=publisher,
        cover_url=covers[0] if covers else "",
        cover_candidates=tuple(covers[1:]),
        price_amount=priced.price_amount if priced else None,
        price_currency=priced.price_currency if priced else "",
        price_kind=priced.price_kind if priced else "",
        price_source=priced.price_source if priced else "",
        metadata_sources=sources,
    )


def lookup_book(isbn_value: str, *, timeout: float = 8.0) -> BookLookupResult:
    """Pobiera metadane wydania na podstawie ISBN z kilku niezależnych źródeł.

    ISBN jest zawsze normalizowany przed wyszukiwaniem, więc myślniki i spacje
    nie wpływają na wynik. Dla polskich wydań najpierw pytamy publiczne API
    Biblioteki Narodowej. Open Library oraz Google Books uzupełniają metadane,
    okładkę i ewentualną cenę. Google Books jest dodatkowo przeszukiwane po
    tytule/wydawcy, gdy wyszukiwanie ``isbn:`` nie zwróci właściwego woluminu.
    """

    isbn = normalize_isbn(isbn_value)
    if not isbn:
        return BookLookupResult(isbn="")

    bn = _bn_result(isbn, timeout=timeout)
    ol = _open_library_result(isbn, timeout=timeout)
    title_hint = (bn.title if bn else "") or (ol.title if ol else "")
    publisher_hint = (bn.publisher if bn else "") or (ol.publisher if ol else "")
    google = _google_books_result(
        isbn,
        timeout=timeout,
        title_hint=title_hint,
        publisher_hint=publisher_hint,
    )
    result = _merge_many((bn, ol, google), isbn)

    # Ostatnia próba okładki po samym ISBN, nawet jeśli żaden katalog nie
    # posiada rekordu bibliograficznego.
    fallback = [
        f"{OPEN_LIBRARY_COVERS}/isbn/{candidate}-L.jpg?default=false"
        for candidate in isbn_variants(isbn)
    ]
    all_covers = _unique_urls((*result.covers(), *fallback))
    result.cover_url = all_covers[0] if all_covers else ""
    result.cover_candidates = tuple(all_covers[1:])
    return result


def cover_cache_path(isbn_value: str) -> Path:
    isbn = normalize_isbn(isbn_value) or "unknown"
    folder = cache_dir() / "covers"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{isbn}.jpg"


def _download_image(url: str, *, timeout: float) -> bytes | None:
    parsed_url = urlparse(url)
    if parsed_url.scheme != "https" or (parsed_url.hostname or "").lower() not in ALLOWED_COVER_HOSTS:
        return None
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
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
    return payload


def download_cover(result: BookLookupResult, *, timeout: float = 8.0) -> Path | None:
    target = cover_cache_path(result.isbn)
    if target.is_file() and target.stat().st_size > 0:
        return target

    # Nie kończymy na pierwszym URL. Brak okładki w Open Library nie powinien
    # blokować kolejnej próby przez Google Books i odwrotnie.
    for cover_url in result.covers():
        payload = _download_image(cover_url, timeout=timeout)
        if payload is None:
            continue
        temporary = target.with_suffix(".tmp")
        try:
            temporary.write_bytes(payload)
            temporary.replace(target)
        except OSError:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            continue
        return target
    return None
