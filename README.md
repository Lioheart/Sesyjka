# Sesyjka GTK4 0.7.0

Natywna aplikacja dla Linuksa zbudowana w Pythonie, GTK4 i Libadwaita. Program kataloguje systemy RPG, podręczniki, suplementy, sesje, graczy i wydawców. Zachowuje zgodność z czterema bazami SQLite projektu źródłowego.

Repozytorium wynikowe: https://github.com/Lioheart/Sesyjka

Projekt źródłowy i atrybucja: https://github.com/ZuraffPL/sesyjka

## Funkcje

Program obsługuje hierarchię systemów gry, podręczników głównych i suplementów. Dostępne są statusy kolekcji i gry, wersje fizyczne, PDF i VTT, język, rok, ISBN, ceny oraz waluty. Tabele mają wyszukiwanie globalne, filtry kolumnowe, sortowanie, zmianę szerokości kolumn i menu kontekstowe.

Sesje są przypisywane do systemów gry. Formularz obsługuje mistrza gry, sesje GM-less, kampanie, jednostrzały, tryb gry, przygody, notatki i grupy graczy. Zapis sesji bez co najmniej jednego istniejącego gracza jest blokowany.

Dostępne są statystyki z tabelami podsumowującymi i wykresami ilości, eksport ZIP, eksport do folderu, eksport XLSX, import z walidacją i kopią zapasową oraz tryb gościa tylko do odczytu.

## Dane użytkownika

Domyślne lokalizacje:

```text
${XDG_DATA_HOME:-~/.local/share}/sesyjka/
${XDG_CONFIG_HOME:-~/.config}/sesyjka/
${XDG_STATE_HOME:-~/.local/state}/sesyjka/
```

Pliki baz:

```text
systemy_rpg.db
sesje_rpg.db
gracze.db
wydawcy.db
```

Log diagnostyczny:

```text
${XDG_STATE_HOME:-~/.local/state}/sesyjka/sesyjka.log
```

## Instalacja z GitHub Release

### Ubuntu i systemy Debianowe

Pobierz plik `sesyjka_X.Y.Z_all.deb`, a następnie:

```bash
sudo apt install ./sesyjka_X.Y.Z_all.deb
```

Pakiet deklaruje zależności GTK4, Libadwaita, PyGObject i openpyxl. Kod aplikacji jest instalowany w `/usr/share/sesyjka`, a program uruchamiający w `/usr/bin/sesyjka`.

Odinstalowanie:

```bash
sudo apt remove sesyjka
```

### Fedora

Pobierz plik `sesyjka-X.Y.Z-1.fc*.noarch.rpm`, a następnie:

```bash
sudo dnf install ./sesyjka-X.Y.Z-1.fc*.noarch.rpm
```

Odinstalowanie:

```bash
sudo dnf remove sesyjka
```

### Pozostałe dystrybucje

Pobierz `sesyjka-X.Y.Z-linux-installer.tar.gz` lub `.zip`, rozpakuj i uruchom:

```bash
chmod +x install-linux.sh uninstall-linux.sh run.sh
./install-linux.sh
```

Instalator ogólny używa:

```text
/opt/sesyjka/
/usr/local/bin/sesyjka
/usr/local/share/applications/
/usr/local/share/metainfo/
/usr/local/share/icons/hicolor/
```

Odinstalowanie z zachowaniem danych:

```bash
./uninstall-linux.sh
```

Całkowite usunięcie danych bieżącego użytkownika:

```bash
./uninstall-linux.sh --purge-data
```

## Uruchomienie lokalne

`run.sh` wyłącznie uruchamia kod z bieżącego katalogu. Nie instaluje programu, nie kopiuje plików i nie modyfikuje systemu.

Ubuntu:

```bash
sudo apt install python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 python3-openpyxl
./run.sh
```

Fedora:

```bash
sudo dnf install python3 python3-gobject gtk4 libadwaita python3-openpyxl
./run.sh
```

Arch Linux:

```bash
sudo pacman -S python python-gobject gtk4 libadwaita python-openpyxl
./run.sh
```

## Aktualizacje

Aplikacja sprawdza najnowsze stabilne wydanie w repozytorium `Lioheart/Sesyjka` podczas uruchamiania, nie częściej niż co 6 godzin. Sprawdzenie można również uruchomić ręcznie przyciskiem aktualizacji w nagłówku lub w oknie „O programie”.

Po wykryciu nowszej wersji aplikacja:

1. wybiera pakiet odpowiadający kanałowi instalacji, czyli DEB, RPM albo instalator ogólny,
2. pobiera pakiet i weryfikuje jego sumę SHA-256,
3. prosi o potwierdzenie uprawnień administratora przez Polkit,
4. uruchamia `apt-get`, `dnf` albo `install-linux.sh`,
5. informuje o konieczności ponownego uruchomienia programu.

Lokalna kopia uruchomiona przez `run.sh` nie jest automatycznie nadpisywana. Program otwiera stronę najnowszego wydania.

Automatyczne sprawdzanie można wyłączyć w oknie „O programie”. Brak programu `pkexec` nie blokuje ręcznego pobrania wydania.

## Automatyczne budowanie Release

Workflow `.github/workflows/release.yml` uruchamia się po opublikowaniu GitHub Release. Tag musi mieć postać `vX.Y.Z`, a numer musi być zgodny z:

```text
pyproject.toml
sesyjka/__init__.py
```

Workflow uruchamia testy i dołącza do Release:

```text
sesyjka_X.Y.Z_all.deb
sesyjka-X.Y.Z-1.fc*.noarch.rpm
sesyjka-X.Y.Z-linux-installer.tar.gz
sesyjka-X.Y.Z-linux-installer.zip
SHA256SUMS
```

Procedura wydania:

1. Zmień wersję w `pyproject.toml`, `sesyjka/__init__.py` i MetaInfo.
2. Zatwierdź zmiany w gałęzi `main`.
3. Utwórz tag `vX.Y.Z` dla tego zatwierdzenia.
4. Utwórz i opublikuj GitHub Release z tym tagiem.
5. Poczekaj na zakończenie workflow „Build release packages”.
6. Sprawdź, czy wszystkie pięć typów zasobów zostało dołączonych do wydania.

Nazwy plików są częścią protokołu aktualizacji. Nie należy ich zmieniać ręcznie.

Szczegóły budowania lokalnego znajdują się w [packaging/README.md](packaging/README.md).

## Testy

```bash
python3 -m compileall -q sesyjka tests
python3 -m unittest discover -s tests -v
bash -n run.sh install-linux.sh uninstall-linux.sh packaging/*.sh
```

Testy obejmują CRUD, integralność między bazami, walidację sesji, migrację schematu, transfer danych, tryb gościa, statystyki, skrypty instalacyjne, pakowanie Release oraz aktualizator.

## Licencja

Port zachowuje licencję CC BY 4.0 i atrybucję projektu źródłowego. Zobacz `LICENSE` i `NOTICE.md`.
