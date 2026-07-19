from __future__ import annotations

import shutil
import sqlite3
import tempfile
import zipfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Sequence

from .config import CORE_DB_FILES, DB_FILES, data_dir


class ReadOnlyDatabaseError(PermissionError):
    pass


class DatabaseManager:
    """Zarządza ścieżkami, inicjalizacją i transferem baz Sesyjki."""

    PRIMARY_TABLES = {
        "systemy_rpg.db": "systemy_rpg",
        "sesje_rpg.db": "sesje_rpg",
        "gracze.db": "gracze",
        "wydawcy.db": "wydawcy",
        "planszowe.db": "planszowe",
    }
    SCHEMA_REQUIREMENTS: dict[str, dict[str, set[str]]] = {
        "wydawcy.db": {
            "wydawcy": {"id", "nazwa", "strona", "kraj"},
        },
        "gracze.db": {
            "gracze": {
                "id",
                "nick",
                "imie_nazwisko",
                "plec",
                "social",
                "glowny_uzytkownik",
                "wazna",
                "grupa",
            },
        },
        "systemy_rpg.db": {
            "systemy_rpg": {
                "id",
                "nazwa",
                "typ",
                "system_glowny_id",
                "typ_suplementu",
                "wydawca_id",
                "fizyczny",
                "pdf",
                "jezyk",
                "status_gra",
                "status_kolekcja",
                "cena_zakupu",
                "waluta_zakupu",
                "cena_sprzedazy",
                "waluta_sprzedazy",
                "vtt",
                "system_glowny_nazwa_custom",
                "system_gry_id",
                "cena_fiz",
                "cena_pdf",
                "cena_vtt",
                "rok_wydania",
                "isbn",
            },
            "systemy_gry": {"id", "nazwa", "wydawca_id", "jezyk", "notatki"},
        },
        "sesje_rpg.db": {
            "sesje_rpg": {
                "id",
                "data_sesji",
                "system_id",
                "liczba_graczy",
                "mg_id",
                "kampania",
                "jednostrzal",
                "tytul_kampanii",
                "tytul_przygody",
                "tryb_gry",
            },
            "sesje_gracze": {"sesja_id", "gracz_id"},
            "sesje_notatki": {"sesja_id", "tresc", "data_modyfikacji"},
        },
        "planszowe.db": {
            "planszowe": {
                "id",
                "nazwa",
                "typ",
                "min_graczy",
                "max_graczy",
                "czas_min",
                "czas_max",
                "minimalny_wiek",
                "cena",
                "waluta",
                "status_gra",
                "status_kolekcja",
                "wydawca_id",
                "wydawca",
                "rok_wydania",
                "notatki",
            },
        },
    }

    def __init__(self, root: Path | None = None) -> None:
        self._own_root = Path(root) if root is not None else data_dir()
        self._own_root.mkdir(parents=True, exist_ok=True)
        self._guest_root: Path | None = None
        self.last_schema_backup: Path | None = None

    @property
    def own_root(self) -> Path:
        return self._own_root

    @property
    def active_root(self) -> Path:
        return self._guest_root or self._own_root

    @property
    def guest_mode(self) -> bool:
        return self._guest_root is not None

    def enter_guest_mode(self, source: Path) -> None:
        source = Path(source)
        missing = [name for name in CORE_DB_FILES if not (source / name).is_file()]
        if missing:
            raise ValueError("Brak wymaganych baz: " + ", ".join(missing))
        found = [name for name in DB_FILES if (source / name).is_file()]
        self._validate_database_files(source, found, require_current_schema=True)
        self._guest_root = source

    def leave_guest_mode(self) -> None:
        self._guest_root = None

    def path(self, filename: str, own: bool = False) -> Path:
        if filename not in DB_FILES:
            raise ValueError(f"Nieznana baza danych: {filename}")
        return (self._own_root if own else self.active_root) / filename

    @contextmanager
    def connect(self, filename: str, write: bool = False) -> Iterator[sqlite3.Connection]:
        if write and self.guest_mode:
            raise ReadOnlyDatabaseError("Tryb gościa jest tylko do odczytu.")
        path = self.path(filename)
        if self.guest_mode and not path.exists():
            raise FileNotFoundError(path)
        if self.guest_mode:
            connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        else:
            connection = sqlite3.connect(path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            if write:
                connection.commit()
        except Exception:
            if write:
                connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        self.last_schema_backup = self._backup_before_schema_update()
        self._init_publishers()
        self._init_players()
        self._init_systems()
        self._init_sessions()
        self._init_board_games()

    def _backup_before_schema_update(self) -> Path | None:
        existing = [self._own_root / name for name in DB_FILES if (self._own_root / name).is_file()]
        if not existing:
            return None
        if not any(self._database_needs_schema_update(path) for path in existing):
            return None
        backup = (
            self._own_root
            / "backups"
            / f"schema-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}"
        )
        backup.mkdir(parents=True, exist_ok=False)
        for source in existing:
            shutil.copy2(source, backup / source.name)
        return backup

    def _database_needs_schema_update(self, database: Path) -> bool:
        requirements = self.SCHEMA_REQUIREMENTS.get(database.name, {})
        try:
            with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
                for table, required_columns in requirements.items():
                    row = connection.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                        (table,),
                    ).fetchone()
                    if row is None:
                        return True
                    existing_columns = self._columns(connection, table)
                    if not required_columns.issubset(existing_columns):
                        return True
        except (sqlite3.DatabaseError, OSError):
            return True
        return False

    @staticmethod
    def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
        return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}

    @classmethod
    def _ensure_columns(
        cls,
        connection: sqlite3.Connection,
        table: str,
        definitions: dict[str, str],
    ) -> None:
        existing = cls._columns(connection, table)
        for name, sql_type in definitions.items():
            if name not in existing:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}")

    def _init_publishers(self) -> None:
        with self.connect("wydawcy.db", write=True) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS wydawcy (
                    id INTEGER PRIMARY KEY,
                    nazwa TEXT NOT NULL,
                    strona TEXT,
                    kraj TEXT
                )
                """
            )
            self._ensure_columns(
                connection,
                "wydawcy",
                {"strona": "TEXT", "kraj": "TEXT"},
            )

    def _init_players(self) -> None:
        with self.connect("gracze.db", write=True) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS gracze (
                    id INTEGER PRIMARY KEY,
                    nick TEXT NOT NULL,
                    imie_nazwisko TEXT,
                    plec TEXT,
                    social TEXT,
                    glowny_uzytkownik INTEGER DEFAULT 0,
                    wazna INTEGER DEFAULT 0,
                    grupa TEXT
                )
                """
            )
            self._ensure_columns(
                connection,
                "gracze",
                {
                    "imie_nazwisko": "TEXT",
                    "plec": "TEXT",
                    "social": "TEXT",
                    "glowny_uzytkownik": "INTEGER DEFAULT 0",
                    "wazna": "INTEGER DEFAULT 0",
                    "grupa": "TEXT",
                },
            )

    def _init_systems(self) -> None:
        with self.connect("systemy_rpg.db", write=True) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS systemy_rpg (
                    id INTEGER PRIMARY KEY,
                    nazwa TEXT NOT NULL,
                    typ TEXT NOT NULL,
                    system_glowny_id INTEGER,
                    typ_suplementu TEXT,
                    wydawca_id INTEGER,
                    fizyczny INTEGER DEFAULT 0,
                    pdf INTEGER DEFAULT 0,
                    jezyk TEXT,
                    status_gra TEXT DEFAULT 'Nie grane',
                    status_kolekcja TEXT DEFAULT 'W kolekcji',
                    cena_zakupu REAL,
                    waluta_zakupu TEXT,
                    cena_sprzedazy REAL,
                    waluta_sprzedazy TEXT,
                    vtt TEXT,
                    system_glowny_nazwa_custom TEXT,
                    system_gry_id INTEGER,
                    cena_fiz REAL,
                    cena_pdf REAL,
                    cena_vtt REAL,
                    rok_wydania INTEGER,
                    isbn TEXT,
                    FOREIGN KEY (system_glowny_id) REFERENCES systemy_rpg(id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS systemy_gry (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nazwa TEXT NOT NULL,
                    wydawca_id INTEGER,
                    jezyk TEXT,
                    notatki TEXT
                )
                """
            )
            self._ensure_columns(
                connection,
                "systemy_rpg",
                {
                    "system_glowny_id": "INTEGER",
                    "typ_suplementu": "TEXT",
                    "wydawca_id": "INTEGER",
                    "fizyczny": "INTEGER DEFAULT 0",
                    "pdf": "INTEGER DEFAULT 0",
                    "jezyk": "TEXT",
                    "status_gra": "TEXT DEFAULT 'Nie grane'",
                    "status_kolekcja": "TEXT DEFAULT 'W kolekcji'",
                    "cena_zakupu": "REAL",
                    "waluta_zakupu": "TEXT",
                    "cena_sprzedazy": "REAL",
                    "waluta_sprzedazy": "TEXT",
                    "vtt": "TEXT",
                    "system_glowny_nazwa_custom": "TEXT",
                    "system_gry_id": "INTEGER",
                    "cena_fiz": "REAL",
                    "cena_pdf": "REAL",
                    "cena_vtt": "REAL",
                    "rok_wydania": "INTEGER",
                    "isbn": "TEXT",
                },
            )

    def _init_sessions(self) -> None:
        with self.connect("sesje_rpg.db", write=True) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS sesje_rpg (
                    id INTEGER PRIMARY KEY,
                    data_sesji TEXT NOT NULL,
                    system_id INTEGER NOT NULL,
                    liczba_graczy INTEGER NOT NULL,
                    mg_id INTEGER,
                    kampania INTEGER DEFAULT 0,
                    jednostrzal INTEGER DEFAULT 0,
                    tytul_kampanii TEXT,
                    tytul_przygody TEXT,
                    tryb_gry TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS sesje_gracze (
                    sesja_id INTEGER NOT NULL,
                    gracz_id INTEGER NOT NULL,
                    PRIMARY KEY (sesja_id, gracz_id),
                    FOREIGN KEY (sesja_id) REFERENCES sesje_rpg(id) ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS sesje_notatki (
                    sesja_id INTEGER PRIMARY KEY,
                    tresc TEXT NOT NULL,
                    data_modyfikacji TEXT NOT NULL,
                    FOREIGN KEY (sesja_id) REFERENCES sesje_rpg(id) ON DELETE CASCADE
                )
                """
            )
            self._ensure_columns(
                connection,
                "sesje_rpg",
                {
                    "mg_id": "INTEGER",
                    "kampania": "INTEGER DEFAULT 0",
                    "jednostrzal": "INTEGER DEFAULT 0",
                    "tytul_kampanii": "TEXT",
                    "tytul_przygody": "TEXT",
                    "tryb_gry": "TEXT",
                },
            )


    def _init_board_games(self) -> None:
        publisher_ids = {
            str(row["nazwa"]).strip().casefold(): int(row["id"])
            for row in self.table_rows(
                "wydawcy.db",
                "SELECT id, nazwa FROM wydawcy",
            )
            if str(row["nazwa"] or "").strip()
        }
        with self.connect("planszowe.db", write=True) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS planszowe (
                    id INTEGER PRIMARY KEY,
                    nazwa TEXT NOT NULL,
                    typ TEXT NOT NULL DEFAULT 'Gra planszowa',
                    min_graczy INTEGER NOT NULL DEFAULT 1,
                    max_graczy INTEGER NOT NULL DEFAULT 1,
                    czas_min INTEGER,
                    czas_max INTEGER,
                    minimalny_wiek INTEGER,
                    cena REAL,
                    waluta TEXT DEFAULT 'PLN',
                    status_gra TEXT DEFAULT 'Nie grane',
                    status_kolekcja TEXT DEFAULT 'W kolekcji',
                    wydawca_id INTEGER,
                    wydawca TEXT,
                    rok_wydania INTEGER,
                    notatki TEXT
                )
                """
            )
            self._ensure_columns(
                connection,
                "planszowe",
                {
                    "typ": "TEXT NOT NULL DEFAULT 'Gra planszowa'",
                    "min_graczy": "INTEGER NOT NULL DEFAULT 1",
                    "max_graczy": "INTEGER NOT NULL DEFAULT 1",
                    "czas_min": "INTEGER",
                    "czas_max": "INTEGER",
                    "minimalny_wiek": "INTEGER",
                    "cena": "REAL",
                    "waluta": "TEXT DEFAULT 'PLN'",
                    "status_gra": "TEXT DEFAULT 'Nie grane'",
                    "status_kolekcja": "TEXT DEFAULT 'W kolekcji'",
                    "wydawca_id": "INTEGER",
                    "wydawca": "TEXT",
                    "rok_wydania": "INTEGER",
                    "notatki": "TEXT",
                },
            )

            # Wersje 0.8.0-0.8.3 przechowywały wydawcę wyłącznie jako tekst.
            # Relacja między osobnymi plikami SQLite jest egzekwowana w Pythonie.
            # Przy migracji wiążemy dokładnie pasujące nazwy bez usuwania pola
            # tekstowego, aby starsze wydania nadal mogły odczytać bazę.
            legacy_rows = connection.execute(
                """
                SELECT id, wydawca
                FROM planszowe
                WHERE wydawca_id IS NULL AND TRIM(COALESCE(wydawca, '')) <> ''
                """
            ).fetchall()
            for row in legacy_rows:
                publisher_id = publisher_ids.get(str(row["wydawca"]).strip().casefold())
                if publisher_id is not None:
                    connection.execute(
                        "UPDATE planszowe SET wydawca_id=? WHERE id=?",
                        (publisher_id, int(row["id"])),
                    )

    def has_active_database(self, filename: str) -> bool:
        if filename not in DB_FILES:
            return False
        return self.path(filename).is_file()

    def next_id(self, filename: str, table: str) -> int:
        with self.connect(filename) as connection:
            row = connection.execute(f"SELECT MAX(id) AS max_id FROM {table}").fetchone()
            return int(row["max_id"] or 0) + 1

    def export_zip(self, destination: Path) -> Path:
        destination = Path(destination)
        if destination.suffix.lower() != ".zip":
            destination = destination.with_suffix(".zip")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for filename in DB_FILES:
                source = self.path(filename, own=True)
                if source.exists():
                    archive.write(source, arcname=filename)
        return destination

    def export_folder(self, destination: Path) -> Path:
        """Copy all application databases into a selected directory."""
        destination = Path(destination)
        destination.mkdir(parents=True, exist_ok=True)
        for filename in DB_FILES:
            source = self.path(filename, own=True)
            if source.exists():
                shutil.copy2(source, destination / filename)
        return destination

    def export_excel(self, destination: Path) -> Path:
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Alignment, Font, PatternFill
        except ImportError as exc:
            raise RuntimeError("Eksport XLSX wymaga pakietu openpyxl.") from exc

        destination = Path(destination)
        if destination.suffix.lower() != ".xlsx":
            destination = destination.with_suffix(".xlsx")
        workbook = Workbook()
        workbook.remove(workbook.active)
        labels = {
            "systemy_rpg.db": "Systemy RPG",
            "sesje_rpg.db": "Sesje RPG",
            "gracze.db": "Gracze",
            "wydawcy.db": "Wydawcy",
            "planszowe.db": "Gry planszowe",
        }
        for filename in DB_FILES:
            source = self.path(filename, own=True)
            if not source.exists():
                continue
            with sqlite3.connect(source) as connection:
                connection.row_factory = sqlite3.Row
                tables = connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
                for table_row in tables:
                    table = str(table_row["name"])
                    title = f"{labels[filename]} - {table}"[:31]
                    sheet = workbook.create_sheet(title)
                    rows = connection.execute(f'SELECT * FROM "{table}"').fetchall()
                    headers = [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')]
                    sheet.append(headers)
                    for cell in sheet[1]:
                        cell.font = Font(color="FFFFFF", bold=True)
                        cell.fill = PatternFill("solid", fgColor="1565C0")
                        cell.alignment = Alignment(horizontal="center")
                    for row in rows:
                        sheet.append([row[header] for header in headers])
                    for column in sheet.columns:
                        width = min(50, max(10, max(len(str(cell.value or "")) for cell in column) + 2))
                        sheet.column_dimensions[column[0].column_letter].width = width
        if not workbook.sheetnames:
            workbook.create_sheet("Brak danych")
        workbook.save(destination)
        return destination

    def inspect_import_source(self, source: Path) -> tuple[Path, list[str], Path | None]:
        source = Path(source)
        cleanup: Path | None = None
        if source.is_dir():
            root = source
        elif source.suffix.lower() == ".zip":
            cleanup = Path(tempfile.mkdtemp(prefix="sesyjka-import-"))
            with zipfile.ZipFile(source) as archive:
                names = {Path(name).name for name in archive.namelist()}
                allowed = [name for name in DB_FILES if name in names]
                if not allowed:
                    shutil.rmtree(cleanup, ignore_errors=True)
                    raise ValueError("Archiwum nie zawiera baz danych Sesyjki.")
                for name in allowed:
                    member = next(item for item in archive.namelist() if Path(item).name == name)
                    with archive.open(member) as src, (cleanup / name).open("wb") as dst:
                        shutil.copyfileobj(src, dst)
            root = cleanup
        else:
            raise ValueError("Wybierz katalog albo archiwum ZIP.")
        found = [name for name in DB_FILES if (root / name).is_file()]
        if not found:
            if cleanup:
                shutil.rmtree(cleanup, ignore_errors=True)
            raise ValueError("Nie znaleziono baz danych Sesyjki.")
        try:
            self._validate_database_files(root, found)
        except ValueError:
            if cleanup:
                shutil.rmtree(cleanup, ignore_errors=True)
            raise
        return root, found, cleanup

    def _validate_database_files(
        self,
        root: Path,
        filenames: Sequence[str],
        *,
        require_current_schema: bool = False,
    ) -> None:
        try:
            for filename in filenames:
                database = Path(root) / filename
                tables = (
                    self.SCHEMA_REQUIREMENTS[filename]
                    if require_current_schema
                    else {self.PRIMARY_TABLES[filename]: set()}
                )
                with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
                    for table, required_columns in tables.items():
                        row = connection.execute(
                            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                            (table,),
                        ).fetchone()
                        if row is None:
                            raise ValueError(
                                f"Plik {filename} nie zawiera wymaganej tabeli {table}."
                            )
                        if required_columns:
                            existing_columns = self._columns(connection, table)
                            if not required_columns.issubset(existing_columns):
                                raise ValueError(
                                    f"Plik {filename} ma niezgodny schemat tabeli {table}."
                                )
                    check = connection.execute("PRAGMA quick_check").fetchone()
                    if check is None or str(check[0]).casefold() != "ok":
                        raise ValueError(
                            f"Kontrola integralności bazy {filename} nie zakończyła się poprawnie."
                        )
        except ValueError:
            raise
        except (sqlite3.DatabaseError, OSError) as exc:
            raise ValueError(
                "Co najmniej jeden plik nie jest poprawną bazą SQLite Sesyjki."
            ) from exc

    def replace_own_databases(self, source: Path, filenames: Sequence[str]) -> Path:
        if self.guest_mode:
            raise ReadOnlyDatabaseError("Najpierw zakończ tryb gościa.")
        backup = self._own_root / "backups" / datetime.now().strftime("%Y%m%d-%H%M%S")
        backup.mkdir(parents=True, exist_ok=True)
        for filename in filenames:
            if filename not in DB_FILES:
                continue
            current = self.path(filename, own=True)
            incoming = Path(source) / filename
            if current.exists():
                shutil.copy2(current, backup / filename)
            shutil.copy2(incoming, current)
        self.initialize()
        return backup

    def table_rows(self, filename: str, query: str, parameters: Sequence[Any] = ()) -> list[sqlite3.Row]:
        with self.connect(filename) as connection:
            return list(connection.execute(query, parameters).fetchall())
