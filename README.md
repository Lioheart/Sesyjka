# Sesyjka GTK4 0.8.6

Natywna aplikacja dla Linuksa zbudowana w Pythonie, GTK4 i Libadwaita. Program kataloguje systemy RPG, podręczniki, suplementy, sesje, graczy, wydawców oraz gry planszowe i karciane.

Repozytorium wynikowe: https://github.com/Lioheart/Sesyjka

Projekt źródłowy i atrybucja: https://github.com/ZuraffPL/sesyjka

## Funkcje

Zakładka **Systemy RPG** obsługuje hierarchię systemów gry, grup organizacyjnych i przypisanych do nich pozycji. Dostępne są statusy kolekcji i gry, format fizyczny, PDF i VTT, język, rok wydania, ISBN, ceny oraz waluty. Tabele używają natywnego stylu Adwaita, wyszukiwania globalnego, filtrów kolumnowych, sortowania, zmiany szerokości kolumn i menu kontekstowego. Niestabilne kolorowanie prywatnych widgetów wierszy `Gtk.ColumnView` zostało usunięte, ponieważ na części wersji GTK prowadziło do błędów dostępności i awarii procesu.

Formularz pozycji RPG zawsze pokazuje nazwę, typ, system RPG, wydawcę, formaty, język, status gry, status kolekcji, rok wydania i ISBN. Dla suplementów udostępnia wielokrotny wybór podgrup zapisywanych separatorem ` | `: scenariusz lub kampania, rozwinięcie zasad, moduł, lorebook lub sourcebook, bestiariusz oraz starter. Pola cen fizycznej, VTT i PDF pojawiają się tylko dla zaznaczonych formatów. Cena łączna jest liczona automatycznie. Cena sprzedaży jest dostępna wyłącznie dla statusów `Na sprzedaż` i `Sprzedane`. Pole języka korzysta z listy PL, ENG, DE, FR, ES, IT lub Inny. Pole waluty zakupu podpowiada popularne kody PLN, USD, EUR i GBP. ISBN-10 i ISBN-13 są walidowane, ale niepoprawna wartość może zostać zapisana po potwierdzeniu ostrzeżenia.

Zakładka **Sesje RPG** przypisuje sesje do systemów gry. Formularz obsługuje mistrza gry, sesje GM-less, kampanie, jednostrzały, tryb gry, przygody, notatki i grupy graczy. Zapis sesji bez co najmniej jednego istniejącego gracza jest blokowany. Sesje można eksportować do iCalendar `.ics` oraz do formatu `.csv` używanego między innymi przez import kalendarza Google.

Zakładka **Gry planszowe** korzysta z osobnej bazy `planszowe.db`. Przechowuje gry planszowe i karciane, zakres liczby graczy, czas rozgrywki, minimalny wiek, cenę, walutę, status gry, status kolekcji, wydawcę, rok wydania. Wydawca jest wybierany bezpośrednio z bazy `wydawcy.db`, a jego usunięcie jest blokowane, gdy pozostaje powiązany z grą.

Statystyki obejmują systemy RPG, sesje, graczy, wydawców, formaty fizyczne i PDF, łączną liczbę planszówek i karcianek oraz sumę cen zakupu wszystkich pozycji RPG i gier stołowych, podaną osobno dla każdej waluty. Wykres gier stołowych pokazuje osobno planszówki i karcianki. Dwie tabele zestawień są rozdzielone odstępem i pionowym separatorem.

Transfer danych obejmuje eksport ZIP, eksport do folderu, eksport XLSX, eksport sesji do ICS i CSV, import z walidacją i kopią zapasową oraz tryb gościa tylko do odczytu.

## Zmiany w 0.8.6

- lista typów pozycji RPG zawiera teraz wyłącznie `Podręcznik Główny`, `Suplement`, `Inne` i `Grupa`
- rekord typu `Grupa` pełni rolę kontenera organizacyjnego dla pozostałych pozycji
- pole `Podręcznik nadrzędny` otrzymało nazwę `Grupa`
- w polu `Grupa` można wybrać wyłącznie rekord typu `Grupa` należący do tego samego systemu RPG
- rekord typu `Grupa` nie może należeć do innej grupy, a zmiana jego typu lub systemu jest blokowana, gdy zawiera pozycje
- zachowano kolumnę `system_glowny_id` i cały dotychczasowy schemat `systemy_rpg.db`
- wycofano kolorowanie wierszy według statusu kolekcji. Tabela używa wyłącznie natywnego tła Adwaita i wyróżnienia zaznaczenia
- przycisk baz danych używa ikony `document-save-symbolic`, a sprawdzanie aktualizacji ikony `software-update-available`

## Zmiany w 0.8.5

- usunięto nieobsługiwane przechodzenie po prywatnych widgetach wierszy `Gtk.ColumnView`, które mogło powodować błędy `GTK_IS_WIDGET`, błędy dostępności i `SIGSEGV`
- wycofano kolorowanie wierszy według statusu kolekcji do czasu zastąpienia tabeli kontrolką udostępniającą publiczny widget całego wiersza
- zaznaczenie rekordu korzysta wyłącznie z bezpiecznego selektora CSS `row:selected`
- aplikacja nadal steruje jasnym i ciemnym wariantem przez `Adw.StyleManager`

## Zmiany w 0.8.4

- formularz systemu gry zawiera wyłącznie nazwę i notatki, bez pól wydawcy oraz języka
- gry planszowe i karciane wybierają wydawcę z bazy `wydawcy.db`, z możliwością szybkiego dodania nowego wydawcy
- `planszowe.db` przechowuje `wydawca_id`, zachowując tekstową nazwę dla zgodności z wersjami 0.8.0-0.8.3
- starsze tekstowe nazwy wydawców są automatycznie wiązane z identyfikatorem przy dokładnym dopasowaniu nazwy
- pole notatek zostało usunięte z formularza gier planszowych i karcianych, bez kasowania istniejącej kolumny ani danych
- adres WWW wydawcy jest klikalny w tabeli i otwiera się w domyślnej przeglądarce

## Zmiany w 0.8.3

- kolory statusu kolekcji są przypisywane do rzeczywistych widgetów całych wierszy `Gtk.ColumnView`, nie do komórek
- zebra-striping jest realizowany selektorem `row:nth-child(even)` na poziomie wiersza
- podgrupy suplementów są zapisywane separatorem ` | ` zgodnie z bazami projektu
- język jest wybierany z listy: PL, ENG, DE, FR, ES, IT lub Inny
- ISBN-10 i ISBN-13 są sprawdzane pod kątem formatu i cyfry kontrolnej, ale ostrzeżenie nie blokuje zapisu
- przycisk baz danych używa ikony `database`

## Zmiany w 0.8.2

- dodano pierwszą wersję kolorowania statusów i pasiastego układu tabel
- pozycja typu `Suplement` obsługuje wielokrotny wybór podgrup
- waluta zakupu ma podpowiedź popularnych kodów PLN, USD, EUR i GBP

## Dane użytkownika i kompatybilność

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
planszowe.db
```

Pierwsze cztery pliki zachowują schematy zgodne z projektem `ZuraffPL/sesyjka`. Nowa funkcja planszówek nie dodaje tabel ani kolumn do tych baz. Jest przechowywana wyłącznie w `planszowe.db`.

Import i tryb gościa nadal akceptują zestaw zawierający tylko cztery oryginalne bazy. W takim przypadku zakładka gier planszowych pozostaje pusta. Eksport tworzony przez wersję 0.8.6 zawiera pięć baz.

Log diagnostyczny:

```text
${XDG_STATE_HOME:-~/.local/state}/sesyjka/sesyjka.log
```

## Diagnostyka motywu

Komunikat:

```text
Using GtkSettings:gtk-application-prefer-dark-theme with libadwaita is unsupported
```

nie pochodzi z przełącznika motywu Sesyjki. Aplikacja używa `Adw.StyleManager`. Ostrzeżenie zwykle oznacza, że w `~/.config/gtk-4.0/settings.ini` znajduje się starszy wpis `gtk-application-prefer-dark-theme`. Można usunąć ten wpis i ponownie uruchomić aplikację.

## Instalacja z GitHub Release

### Ubuntu i systemy Debianowe

Pobierz plik `sesyjka_X.Y.Z_all.deb`, a następnie:

```bash
sudo apt install ./sesyjka_X.Y.Z_all.deb
```

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

Aplikacja sprawdza najnowsze stabilne wydanie w repozytorium `Lioheart/Sesyjka` podczas uruchamiania, nie częściej niż co 6 godzin. Sprawdzenie można również uruchomić ręcznie przyciskiem aktualizacji w nagłówku lub w oknie `O programie`.

Po wykryciu nowszej wersji aplikacja wybiera pakiet DEB, RPM albo instalator ogólny, pobiera plik, weryfikuje SHA-256 i uruchamia aktualizację przez Polkit. Lokalna kopia uruchomiona przez `run.sh` nie jest automatycznie nadpisywana. W takim przypadku program otwiera stronę najnowszego wydania.

## Automatyczne budowanie Release

Workflow `.github/workflows/release.yml` uruchamia się po opublikowaniu GitHub Release albo ręcznie dla istniejącego tagu. Tag musi mieć postać `vX.Y.Z`, a numer musi być zgodny z `pyproject.toml` i `sesyjka/__init__.py`.

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
5. Poczekaj na zakończenie workflow `Build release packages`.
6. Sprawdź komplet plików i `SHA256SUMS`.

Nazwy plików są częścią protokołu aktualizacji i nie powinny być zmieniane ręcznie.

Szczegóły budowania lokalnego znajdują się w [packaging/README.md](packaging/README.md).

## Testy

```bash
python3 -m compileall -q sesyjka tests
python3 -m unittest discover -s tests -v
bash -n run.sh install-linux.sh uninstall-linux.sh packaging/*.sh
```

Testy obejmują CRUD pięciu baz, zgodność zestawu czterech baz projektu źródłowego, walidację sesji, migrację schematu, transfer danych, eksport kalendarza, dynamiczne ceny, statystyki, skrypty instalacyjne, pakowanie Release oraz aktualizator.

## Licencja

Port zachowuje licencję CC BY 4.0 i atrybucję projektu źródłowego. Zobacz `LICENSE` i `NOTICE.md`.
