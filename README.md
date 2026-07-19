# Sesyjka GTK4 0.6.4

Natywny port programu Sesyjka dla Linuksa, zbudowany w Pythonie, GTK4 i Libadwaita. Port zachowuje cztery bazy SQLite projektu źródłowego i rozdziela logikę danych od warstwy prezentacji.

## Najważniejsze funkcje

Program obsługuje katalog systemów RPG, podręczników i suplementów w układzie hierarchicznym. Dostępne są statusy kolekcji i gry, wersje fizyczne i PDF, język, VTT, ceny, waluty, rok wydania oraz ISBN. Tabele mają wyszukiwanie globalne, filtry kolumnowe, sortowanie, zmianę szerokości kolumn i menu kontekstowe z edycją oraz usuwaniem.

Sesje są przypisywane do rekordów z katalogu systemów gry. Formularz obsługuje mistrza gry, sesje GM-less, tryb gry, kampanię, jednostrzał, tytuły, notatki, graczy i szybki wybór grupy. Zapis sesji bez co najmniej jednego istniejącego gracza jest blokowany.

Dostępne są osobne moduły graczy, wydawców i statystyk. Statystyki odświeżają się po operacjach CRUD i pokazują zestawienia oraz natywne wykresy ilości GTK4.

Transfer danych obejmuje eksport ZIP, eksport czterech baz do folderu, eksport XLSX, import ZIP lub folderu z walidacją i kopią zapasową, a także tryb gościa tylko do odczytu.

Pełne porównanie z projektem źródłowym znajduje się w [FUNCTIONALITY_AUDIT.md](FUNCTIONALITY_AUDIT.md).

## Dane i zgodność

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

Przed zmianą starszego schematu program tworzy kopię istniejących baz w katalogu `backups/schema-...`. Import zastępujący własne bazy również tworzy kopię zapasową. Wszystkie połączenia w warstwie danych włączają `PRAGMA foreign_keys = ON`. Odwołania pomiędzy osobnymi plikami SQLite są sprawdzane w Pythonie.

Log diagnostyczny jest rotowany i zapisywany jako:

```text
${XDG_STATE_HOME:-~/.local/state}/sesyjka/sesyjka.log
```

## Uruchomienie lokalne

`run.sh` wyłącznie uruchamia kod z bieżącego katalogu. Nie instaluje programu, nie kopiuje plików i nie tworzy wpisu w menu aplikacji.

Wymagane pakiety systemowe dla Debiana lub Ubuntu:

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

Można wskazać inny interpreter:

```bash
SESYJKA_PYTHON=/ścieżka/do/python3 ./run.sh
```

## Instalacja systemowa

```bash
chmod +x install-linux.sh uninstall-linux.sh run.sh
./install-linux.sh
```

Skrypt używa `sudo`, gdy nie jest uruchomiony jako administrator. Domyślnie instaluje:

```text
/opt/sesyjka/
/usr/local/bin/sesyjka
/usr/local/share/applications/io.github.zuraffpl.Sesyjka.desktop
/usr/local/share/metainfo/io.github.zuraffpl.Sesyjka.metainfo.xml
/usr/local/share/icons/hicolor/
```

Po instalacji program można uruchomić z menu pulpitu lub poleceniem:

```bash
sesyjka
```

## Odinstalowanie systemowe

Z katalogu źródłowego:

```bash
./uninstall-linux.sh
```

Albo z katalogu instalacji:

```bash
sudo /opt/sesyjka/uninstall-linux.sh
```

Domyślnie deinstalator pozostawia dane użytkownika. Całkowite usunięcie danych bieżącego użytkownika:

```bash
./uninstall-linux.sh --purge-data
```

Bez pytania o potwierdzenie:

```bash
./uninstall-linux.sh --purge-data --yes
```

Skrypt nie usuwa danych innych użytkowników ani danych instalacji Flatpak.

## Flatpak i Flathub

Lokalny manifest znajduje się w `flatpak/io.github.zuraffpl.Sesyjka.yml`. Pakiet nie ma stałego dostępu do katalogu domowego. Wybór plików odbywa się przez natywne okna GTK i portal dokumentów.

```bash
flatpak remote-add --user --if-not-exists flathub \
  https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak install --user flathub \
  org.flatpak.Builder org.gnome.Platform//50 org.gnome.Sdk//50
./flatpak/build-local.sh
flatpak run io.github.zuraffpl.Sesyjka
```

Instrukcja przygotowania zgłoszenia znajduje się w [FLATHUB.md](FLATHUB.md).

Interfejs użytkownika jest obecnie polskojęzyczny. Zgodnie z aktualnymi zasadami Flathub nowe zgłoszenie wymaga kompletnej lokalizacji angielskiej albo zaakceptowanego wyjątku. Manifest, metadane i piaskownica są przygotowane technicznie, ale publikacja nie jest gwarantowana bez spełnienia tego wymagania.

## Zrzuty ekranu

Katalog `screenshots/` zawiera wszystkie 11 plików przekazanych do wydania:

```text
image.png
image2.png
image3.png
image4.png
image5.png
image6.png
image7.png
image8.png
image9.png
image10.png
image11.png
```

MetaInfo odwołuje się do 10 reprezentatywnych obrazów, ponieważ wytyczne jakości Flathub zalecają dla dużych aplikacji od 6 do 10 zrzutów.

## Testy

```bash
python3 -m compileall -q sesyjka tests
python3 -m unittest discover -s tests -v
bash -n run.sh install-linux.sh uninstall-linux.sh flatpak/build-local.sh
```

Testy obejmują CRUD, walidację powiązań pomiędzy bazami, sesje bez graczy, migrację schematu z kopią zapasową, eksport ZIP i folderu, kontrolę importu, tryb gościa, statystyki, skrypty instalacyjne, zasoby pulpitu i pakowanie Flatpak.

## Licencja

Port zachowuje licencję CC BY 4.0 oraz atrybucję projektu źródłowego. Zobacz `LICENSE` i `NOTICE.md`.
