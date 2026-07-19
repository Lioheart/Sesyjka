# Audyt migracji do GTK4 i Libadwaita

## Architektura

| Obszar | Implementacja GTK4 |
|---|---|
| Aplikacja i okno | `Adw.Application`, `Adw.ApplicationWindow` |
| Nagłówek | `Adw.HeaderBar` |
| Nawigacja | `Gtk.Stack`, `Gtk.StackSwitcher` |
| Tabele | `Gtk.ColumnView`, `Gio.ListStore`, `Gtk.SingleSelection` |
| Sortowanie | `Gtk.SortListModel`, `Gtk.CustomSorter`, sortowanie hierarchiczne |
| Filtry | filtr globalny i osobne filtry kolumnowe |
| Menu kontekstowe | `Gtk.GestureClick`, `Gtk.Popover`, ikony symboliczne |
| Formularze | `Gtk.Entry`, `Gtk.DropDown`, `Gtk.CheckButton`, `Gtk.TextView` |
| Dialogi | modalne `Adw.Window` z rodzicem przejściowym |
| Wybór plików | `Gtk.FileChooserNative` |
| Motyw | `Adw.StyleManager` z `FORCE_LIGHT` i `FORCE_DARK` |
| Skalowanie tekstu | centralny dostawca CSS od 80 do 140 procent |
| Ścieżki | katalogi XDG, bez ścieżek specyficznych dla Windows |

## Dane

Zachowane są pliki `systemy_rpg.db`, `sesje_rpg.db`, `gracze.db` i `wydawcy.db`. Port utrzymuje tabele `systemy_rpg`, `systemy_gry`, `sesje_rpg`, `sesje_gracze`, `sesje_notatki`, `gracze` oraz `wydawcy`. Nowa funkcja planszówek i karcianek korzysta wyłącznie z osobnego pliku `planszowe.db` i tabeli `planszowe`. Nie dodaje tabel ani kolumn do czterech plików projektu źródłowego.

Przed migracją starszego schematu wszystkie istniejące bazy są kopiowane do `backups/schema-...`. Inicjalizacja tworzy brakujące tabele i kolumny bez usuwania rekordów. Import ZIP i folderu waliduje główne tabele oraz integralność SQLite, a następnie tworzy osobną kopię zapasową przed zastąpieniem danych.

Każde połączenie ustawia `sqlite3.Row` i `PRAGMA foreign_keys = ON`. Relacje wewnątrz jednego pliku SQLite są chronione przez klucze obce. Relacje pomiędzy czterema bazami projektu źródłowego są sprawdzane w warstwie `Repository` przed zapisem. Usuwanie gracza, wydawcy, systemu gry lub podręcznika jest blokowane, gdy utworzyłoby osierocone odwołanie.

## Tabele i hierarchia

Widok systemów grupuje rekordy jako system gry, podręcznik główny i pozycje podrzędne. Sortowanie odbywa się wewnątrz gałęzi. Tabele płaskie sortują po kliknięciu nagłówka. Każda tabela CRUD ma filtr globalny, filtry poszczególnych kolumn, zmianę szerokości kolumn, dwuklik i menu prawego przycisku.

## Formularz pozycji RPG

Pola podstawowe są stale widoczne. Pola cen fizycznej, PDF i VTT pojawiają się tylko po zaznaczeniu odpowiedniego formatu. Cena łączna jest wyliczana automatycznie. Cena i waluta sprzedaży są pokazywane tylko dla statusu kolekcji `Na sprzedaż` lub `Sprzedane`.

## Sesje

Pole System korzysta z `systemy_gry`, a nie z nazw suplementów. Zapis wymaga istniejącego systemu i co najmniej jednego istniejącego gracza. Mistrz gry jest opcjonalny. Grupy graczy mogą być zaznaczane zbiorczo. Notatki są przechowywane w tabeli `sesje_notatki`. Sesje można eksportować jako standardowy plik iCalendar `.ics` albo CSV zgodny z typowym importem kalendarza.

## Statystyki

Agregacja odbywa się w `Repository.statistics()`, poza widgetami. Widok renderuje liczniki, dwie tabele podsumowujące i przełączane wykresy ilości. Licznik planszówek i karcianek otwiera wykres z osobnymi słupkami dla obu typów. Po każdej operacji CRUD statystyki są odświeżane przez wspólny mechanizm stron.

## Linux

`run.sh` tylko uruchamia źródła. `install-linux.sh` wykonuje instalację systemową do `/opt` i `/usr/local`. `uninstall-linux.sh` usuwa tę instalację i opcjonalnie dane bieżącego użytkownika. Ikona Wayland jest instalowana z Desktop Entry zgodnym z `application-id`.

## Pakowanie wydań

Wersja wynikowa buduje pakiety DEB, RPM i instalator ogólny przez GitHub Actions po opublikowaniu wydania. Wcześniejsze pliki Flatpak i Flathub zostały usunięte z bieżącego drzewa projektu.

## Kontrole wydania

1. Kompilacja przez `compileall`.
2. Testy domenowe bez uruchamiania GTK.
3. Testy CRUD, migracji, backupu, importu, eksportu i trybu gościa.
4. Testy integralności powiązań pomiędzy bazami.
5. Testy źródłowe tabel, motywu, popoverów, statystyk i ikony Wayland.
6. Testy pakietów Release, metadanych, sum kontrolnych i aktualizatora.
7. Kontrola składni skryptów Bash.
8. Skan kodu pod kątem Tkintera, CustomTkintera i tksheet.
