from __future__ import annotations

import re
from typing import Any

LANGUAGE_CHOICES = ("PL", "ENG", "DE", "FR", "ES", "IT", "Inny")


def normalize_language_choice(value: Any, default: str = "PL") -> str:
    """Mapuje starsze oznaczenia języka na wartości formularza GTK4."""

    raw = str(value or default).strip()
    aliases = {
        "EN": "ENG",
        "ENGLISH": "ENG",
        "ANGIELSKI": "ENG",
        "POLSKI": "PL",
        "GERMAN": "DE",
        "NIEMIECKI": "DE",
        "FRENCH": "FR",
        "FRANCUSKI": "FR",
        "SPANISH": "ES",
        "HISZPAŃSKI": "ES",
        "ITALIAN": "IT",
        "WŁOSKI": "IT",
    }
    normalized = aliases.get(raw.upper(), raw.upper())
    return normalized if normalized in LANGUAGE_CHOICES[:-1] else "Inny"


def is_valid_isbn(value: str) -> bool:
    """Sprawdza format i cyfrę kontrolną ISBN-10 albo ISBN-13.

    Pusty numer jest poprawny, ponieważ pole ISBN jest opcjonalne. Separatory
    w postaci spacji i łączników są ignorowane. Funkcja nie modyfikuje danych,
    ponieważ interfejs ma jedynie ostrzegać, a nie blokować zapis.
    """

    compact = re.sub(r"[\s-]+", "", value)
    if not compact:
        return True

    if re.fullmatch(r"\d{9}[\dXx]", compact):
        digits = [int(character) for character in compact[:9]]
        check = 10 if compact[-1].upper() == "X" else int(compact[-1])
        weighted = sum((10 - index) * digit for index, digit in enumerate(digits))
        return (weighted + check) % 11 == 0

    if re.fullmatch(r"\d{13}", compact):
        digits = [int(character) for character in compact]
        weighted = sum(
            digit * (1 if index % 2 == 0 else 3)
            for index, digit in enumerate(digits[:12])
        )
        expected = (10 - weighted % 10) % 10
        return digits[-1] == expected

    return False
