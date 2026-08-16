# Sesyjka GTK4 0.9.8

Natywna aplikacja dla Linuksa zbudowana w Pythonie, GTK4 i Libadwaita. Program kataloguje systemy RPG, podręczniki, suplementy, sesje, graczy, wydawców oraz gry planszowe i karciane.

Repozytorium wynikowe: https://github.com/Lioheart/Sesyjka

Projekt źródłowy i atrybucja: https://github.com/ZuraffPL/sesyjka

## Sesyjka Cloud 0.9.8

Sesyjka działa teraz w modelu **offline-first**. Wszystkie dotychczasowe bazy SQLite nadal są lokalnym źródłem danych i program działa bez Internetu. Osobna baza `sync.db` przechowuje wyłącznie stan synchronizacji, identyfikator urządzenia i konflikty. Nie dodaje żadnych kolumn ani tabel do `systemy_rpg.db`, `sesje_rpg.db`, `gracze.db`, `wydawcy.db` ani `planszowe.db`. Nowa biblioteka cyfrowa korzysta z osobnego `zasoby.db`, więc cztery bazy projektu źródłowego pozostają bez zmian.

Chmura korzysta z **Supabase Auth** oraz tabeli `sesyjka_records` chronionej przez Row Level Security. Produkcyjny Project URL i publishable key są zapisane w aplikacji. Użytkownik końcowy nie konfiguruje Supabase i po prostu wybiera `Zaloguj przez Discord`. Klucz `secret` ani `service_role` nie może być umieszczany w kliencie desktopowym.

Konfiguracja backendu wykonywana jest jeden raz przez administratora projektu Sesyjka:

1. W `Authentication -> Providers -> Discord` włącz Discord i wpisz Client ID oraz Client Secret z Discord Developer Portal.
2. W Discord Developer Portal jako OAuth2 Redirect URI ustaw `https://rjevhlnscdodgoaztxao.supabase.co/auth/v1/callback`.
3. W `Authentication -> URL Configuration -> Redirect URLs` dodaj `http://127.0.0.1:8765/auth/callback`.
4. W Supabase SQL Editor wykonaj plik `supabase/schema.sql`, który tworzy tabelę synchronizacji i polityki RLS.

Szczegółowa instrukcja znajduje się w `supabase/README.md`. Deweloper może nadal tymczasowo nadpisać produkcyjny backend przez `SESYJKA_SUPABASE_URL` i `SESYJKA_SUPABASE_KEY`.

Synchronizacja działa ręcznie oraz automatycznie. Po lokalnej zmianie uruchamiana jest z krótkim opóźnieniem, a dodatkowo aplikacja wykonuje synchronizację okresową. Brak sieci nie blokuje CRUD. W nagłówku widoczny jest stan `Cloud`, godzina ostatniej synchronizacji albo liczba konfliktów.

Jeżeli ten sam rekord zmienił się po obu stronach od ostatniej synchronizacji, Sesyjka nie nadpisuje go automatycznie. Okno konfliktów pokazuje lokalny i chmurowy JSON oraz pozwala jawnie wybrać `Zachowaj lokalne` albo `Zachowaj chmurę`. Usunięcia są synchronizowane jako tombstone, dlatego można propagować je między urządzeniami.

Sesyjka nie otrzymuje ani nie zapisuje hasła Discord. Logowanie odbywa się w domyślnej przeglądarce w przepływie OAuth PKCE. Token odświeżania jest chroniony uprawnieniami pliku `0600`, ale w wersji 0.9.8 nie jest szyfrowany przez Sesyjkę. Nie kopiuj pliku sesji między użytkownikami ani urządzeniami. Token sesji jest przechowywany w `${XDG_CONFIG_HOME:-~/.config}/sesyjka/cloud-session.json` z prawami `0600`.

## Funkcje

Zakładka **Systemy RPG** obsługuje hierarchię systemów gry, grup organizacyjnych i przypisanych do nich pozycji. Dostępne są statusy kolekcji i gry, format fizyczny, PDF i VTT, język, rok wydania, ISBN, ceny oraz waluty. Tabele używają natywnego stylu Adwaita, wyszukiwania globalnego, filtrów kolumnowych, sortowania, zmiany szerokości kolumn i menu kontekstowego. Niestabilne kolorowanie prywatnych widgetów wierszy `Gtk.ColumnView` zostało usunięte, ponieważ na części wersji GTK prowadziło do błędów dostępności i awarii procesu.

Formularz pozycji RPG zawsze pokazuje nazwę, typ, system RPG, wydawcę, formaty, język, status gry, status kolekcji, rok wydania i ISBN. Dla suplementów udostępnia wielokrotny wybór podgrup zapisywanych separatorem ` | `: scenariusz lub kampania, rozwinięcie zasad, moduł, lorebook lub sourcebook, bestiariusz oraz starter. Pola cen fizycznej, VTT i PDF pojawiają się tylko dla zaznaczonych formatów. Cena łączna jest liczona automatycznie. Cena sprzedaży jest dostępna wyłącznie dla statusów `Na sprzedaż` i `Sprzedane`. Pole języka korzysta z listy PL, ENG, DE, FR, ES, IT lub Inny. Pole waluty zakupu podpowiada popularne kody PLN, USD, EUR i GBP. ISBN-10 i ISBN-13 są walidowane, ale niepoprawna wartość może zostać zapisana po potwierdzeniu ostrzeżenia.

Zakładka **Sesje RPG** przypisuje sesje do systemów gry. Formularz obsługuje mistrza gry, sesje GM-less, kampanie, jednostrzały, tryb gry, przygody, notatki i grupy graczy. Zapis sesji bez co najmniej jednego istniejącego gracza jest blokowany. Dla zaznaczonej sesji menu `Kalendarz` otwiera w przeglądarce wstępnie wypełnione wydarzenie Google Calendar. Dla Apple/iCloud tworzony jest pojedynczy plik `.ics` w katalogu Pobrane/Downloads i otwierany jest iCloud Calendar. Nadal dostępny jest eksport wszystkich sesji do ICS i CSV.


Zakładka **Zasoby cyfrowe** korzysta z osobnej bazy `zasoby.db`. Zasób reprezentuje PDF, zawartość VTT, stronę dostawcy albo inny materiał cyfrowy i może być powiązany z pozycją RPG. Jeden zasób może mieć wiele lokalizacji, na przykład plik na laptopie, kopię na NAS oraz stronę zakupu. Lokalnych plików Sesyjka nie kopiuje do swojej bazy.

Pliki są organizowane przez **magazyny**. Magazyn ma stabilny UUID oraz lokalny katalog bazowy, a lokalizacja zasobu przechowuje tylko ścieżkę względną. Dzięki temu ten sam magazyn logiczny może wskazywać `/mnt/NAS/RPG` na jednym komputerze i `/home/user/NAS/RPG` na drugim. Mapowania katalogów są ustawieniami urządzenia i nie są wysyłane do Cloud. Zasoby oraz ich logiczne lokalizacje są synchronizowane. Jeżeli po synchronizacji pojawi się UUID magazynu nieznany na drugim komputerze, przycisk `Powiąż brakujące` pozwala wskazać odpowiadający mu lokalny katalog.

`Skanuj PDF` indeksuje wybrany katalog rekurencyjnie, liczy SHA-256 i próbuje powiązać plik z pozycją RPG na podstawie nazwy. Automatyczne powiązanie następuje tylko przy wysokiej pewności. Hash pozwala rozpoznać ten sam plik po przeniesieniu i ogranicza duplikaty. Kliknięcie `Otwórz` wybiera preferowaną dostępną lokalizację lokalną, a jeśli jej nie ma, może otworzyć zapisany adres WWW.

Integracja **DriveThruRPG** jest oznaczona jako eksperymentalna. Sesyjka przyjmuje Application Key z włączonym `My Library Access`, pobiera listę zakupów i plików, zapisuje metadane, ISBN, wydawcę, nazwę pliku, dostępne sumy kontrolne i link do produktu, a następnie próbuje powiązać zasób z istniejącą pozycją RPG. Przycisk `Otwórz My Library` prowadzi do aktualnego adresu `https://www.drivethrurpg.com/en/mylibrary`. Duże pliki nie są automatycznie pobierane. Application Key jest zapisywany wyłącznie lokalnie w `${XDG_CONFIG_HOME:-~/.config}/sesyjka/drivethrurpg.json` z prawami `0600` i nie jest synchronizowany do Sesyjka Cloud. Stabilnym rozwiązaniem awaryjnym pozostaje skanowanie katalogu, do którego pobrano bibliotekę DriveThruRPG.

Zakładka **Gry planszowe** korzysta z osobnej bazy `planszowe.db`. Przechowuje gry planszowe i karciane, zakres liczby graczy, czas rozgrywki, minimalny wiek, cenę, walutę, status gry, status kolekcji, wydawcę, rok wydania. Wydawca jest wybierany bezpośrednio z bazy `wydawcy.db`, a jego usunięcie jest blokowane, gdy pozostaje powiązany z grą.

Statystyki obejmują systemy RPG, sesje, graczy, wydawców, formaty fizyczne i PDF, łączną liczbę planszówek i karcianek oraz sumę cen zakupu wszystkich pozycji RPG i gier stołowych, podaną osobno dla każdej waluty. Wykres gier stołowych pokazuje osobno planszówki i karcianki. Dwie tabele zestawień są rozdzielone odstępem i pionowym separatorem.

Transfer danych obejmuje eksport ZIP, eksport do folderu, eksport XLSX, eksport sesji do ICS i CSV, import z walidacją i kopią zapasową oraz tryb gościa tylko do odczytu.

Formularz pozycji RPG ma dzielony układ. Około 60% szerokości zajmują pola edycji, a prawa część pokazuje dane znalezione dla ISBN: okładkę, tytuł, rok wydania, wydawcę i ewentualną informacyjną cenę online. Metadane są pobierane na żądanie oraz automatycznie przy otwarciu rekordu z zapisanym ISBN. Puste pola nazwy i roku są uzupełniane automatycznie. Jeżeli wydawca znaleziony online już istnieje w `wydawcy.db`, może zostać automatycznie dopasowany. Istniejące wartości można zastąpić przyciskiem `Użyj danych z ISBN`. Jeśli lokalna cena nie jest podana, dostępna cena z Google Books może zostać pokazana i ręcznie zastosowana do wybranego formatu. Cena Google Books może dotyczyć e-booka i jest jawnie oznaczana jako informacyjna.

Wyszukiwanie ISBN korzysta z publicznego API Biblioteki Narodowej, Open Library oraz Google Books. ISBN jest normalizowany przed wyszukiwaniem, dlatego myślniki i spacje nie mają wpływu na wynik. Program wylicza również odpowiadający ISBN-10 lub ISBN-13 i próbuje oba identyfikatory. Google Books jest przeszukiwane kolejno po `isbn:`, po samym numerze oraz, gdy katalog biblioteczny dostarczy tytuł, także po tytule i wydawcy. Okładki są pobierane z wielu kandydatów. Jeżeli API Google nie zwraca `imageLinks`, program próbuje front cover po identyfikatorze woluminu Google Books. Okładki są zapisywane w `${XDG_CACHE_HOME:-~/.cache}/sesyjka/covers/`, a metadane i informacja o zakończonej próbie pobrania okładki w `${XDG_CACHE_HOME:-~/.cache}/sesyjka/books/`. Automatyczne otwarcie rekordu najpierw korzysta z tego cache. Przycisk `Pobierz z ISBN` wymusza odświeżenie z internetu. Opcjonalnie można ustawić `SESYJKA_GOOGLE_BOOKS_API_KEY`.

## Zmiany w 0.9.8

- gdy produkt DriveThruRPG zawiera wiele plików, każdy importowany zasób używa nazwy konkretnego pliku zamiast powielonej nazwy produktu
- preferowana jest przyjazna nazwa pliku zwracana przez API. Gdy jej brakuje, używana jest nazwa pliku bez rozszerzenia
- nazwa produktu jest zachowywana osobno do automatycznego dopasowania zasobu do pozycji RPG, dzięki czemu np. karta postaci nadal pozostaje powiązana z właściwym podręcznikiem
- ponowna synchronizacja aktualizuje nazwy zasobów już zaimportowanych w 0.9.7, ponieważ identyfikatory zewnętrzne DriveThruRPG pozostają bez zmian
- brak zmian schematów baz danych użytkownika

## Zmiany w 0.9.7

- naprawiono autoryzację biblioteki DriveThruRPG zgodnie z bieżącą implementacją oficjalnego SDK. JWT jest najpierw wysyłany jako surowa wartość nagłówka `Authorization`, bez prefiksu `Bearer`
- zachowano jednokrotny fallback `Authorization: Bearer <token>` na wypadek backendu zgodnego ze starszym opisem OpenAPI
- `POST /auth_key` wysyła teraz pusty obiekt JSON `{}` razem z Application Key w parametrze zapytania, tak jak bieżący SDK
- błędy 401 z `auth_key` są raportowane jako problem Application Key, natomiast 401 z `order_products` jako problem tokenu JWT. Program nie sugeruje już błędnego klucza, gdy serwer odrzucił token sesji
- dodano testy regresyjne dla surowego JWT, fallbacku Bearer, body żądania uwierzytelniania i rozróżniania błędów 401
- brak zmian schematów baz danych użytkownika

## Zmiany w 0.9.6

- naprawiono transport HTTP integracji DriveThruRPG. Sesyjka rozpoznaje i rozpakowuje odpowiedzi `gzip` oraz `deflate`, a jednocześnie domyślnie prosi API o odpowiedź `identity`
- poprawiono nagłówek autoryzacji dla biblioteki DriveThruRPG do wymaganego formatu `Authorization: Bearer <token>`
- parser `order_products` został dostosowany do paginowanego formatu JSON:API z polami `links`, `meta`, `data` i `included`
- nazwa wydawcy jest odczytywana także z obiektów `Publisher` w sekcji `included` na podstawie `royaltyPublisherId`
- zachowano kompatybilnościowy parser bezpośredniej listy produktów na wypadek starszych wariantów odpowiedzi
- link `Otwórz My Library` pozostaje ustawiony na `https://www.drivethrurpg.com/en/mylibrary`
- brak zmian schematów baz danych użytkownika

## Zmiany w 0.9.4

- dodano osobną bazę `zasoby.db` dla PDF, VTT, URL i innych zasobów cyfrowych
- dodano zakładkę `Zasoby cyfrowe` z sortowaniem, filtrami, otwieraniem zasobów i wieloma lokalizacjami
- dodano logiczne magazyny `Lokalny`, `NAS` i `USB`, przechowujące ścieżki względne zamiast zależnych od komputera ścieżek absolutnych
- dodano możliwość mapowania zsynchronizowanego UUID magazynu na inny katalog na kolejnym urządzeniu
- dodano skanowanie katalogów PDF z SHA-256 i ostrożnym automatycznym dopasowaniem do pozycji RPG
- dodano eksperymentalną synchronizację metadanych biblioteki DriveThruRPG przez Application Key z `My Library Access`
- zasoby i logiczne lokalizacje uczestniczą w Sesyjka Cloud, ale lokalne mapowania katalogów i Application Key nie są synchronizowane
- standardowy eksport/import obejmuje teraz sześć baz użytkownika. `sync.db` nadal pozostaje poza eksportem
- nie zmieniono schematów czterech baz projektu źródłowego

## Zmiany w 0.9.3

- naprawiono źródło RPM, które pomijało katalog `supabase/`, przez co testy `%check` kończyły się błędem `FileNotFoundError: supabase/schema.sql`
- ujednolicono przygotowywanie drzewa źródłowego dla instalatora ogólnego i RPM przez wspólną funkcję `stage_release_source`
- pakiet RPM instaluje również `supabase/schema.sql` i `supabase/README.md` jako dokumentację administratora backendu
- dodano test regresyjny kontrolujący obecność plików konfiguracji Sesyjka Cloud w źródle RPM
- brak zmian schematów baz użytkownika i brak zmian protokołu synchronizacji

## Zmiany w 0.9.2

- wbudowano produkcyjny `SUPABASE_URL` i publishable key, usuwając pola konfiguracyjne Supabase z GUI
- pozostawiono zmienne `SESYJKA_SUPABASE_URL` i `SESYJKA_SUPABASE_KEY` jako opcjonalny override developerski
- dodano menu `Kalendarz` dla zaznaczonej sesji RPG
- Google Calendar otwiera w przeglądarce formularz nowego wydarzenia z wypełnioną datą, systemem, kampanią lub przygodą, MG, graczami i notatkami
- Apple/iCloud Calendar otrzymuje pojedynczą sesję przez wygenerowany plik ICS, zapisywany w katalogu Downloads/Pobrane, po czym otwierany jest iCloud Calendar
- nie zmieniono schematów pięciu baz danych z danymi użytkownika

## Zmiany w 0.9.1

- usunięto z GUI rejestrację i logowanie e-mail + hasło do Sesyjka Cloud
- dodano logowanie przez konto Discord za pośrednictwem Supabase Auth
- zastosowano OAuth Authorization Code + PKCE z `S256`
- callback aplikacji nasłuchuje wyłącznie na `127.0.0.1:8765`
- pierwsze logowanie Discord automatycznie tworzy użytkownika Supabase Auth
- po poprawnym logowaniu synchronizacja lokalna/chmurowa uruchamia się automatycznie

## Zmiany w 0.9.0

- dodano osobną bazę `sync.db` bez modyfikowania schematów istniejących baz danych
- dodano konta użytkowników przez Supabase Auth, rejestrację e-mail + hasło, logowanie, odświeżanie sesji i wylogowanie
- dodano synchronizację lokalnych rekordów z Supabase Data REST API w modelu offline-first
- synchronizacja działa ręcznie, przy starcie, okresowo oraz po lokalnych operacjach CRUD z opóźnieniem debounce
- dodano status Cloud w nagłówku aplikacji z informacją o logowaniu, trybie offline, czasie ostatniej synchronizacji i konfliktach
- dodano jawne konflikty, porównanie lokalnej i chmurowej wersji rekordu oraz wybór wersji do zachowania
- usunięcia są propagowane jako tombstone zamiast bezpowrotnego kasowania rekordu chmurowego
- dodano gotowy `supabase/schema.sql` z RLS ograniczającym rekordy do `auth.uid()` zalogowanego użytkownika
- tytuł `Sesyjka` w nagłówku jest większy
- nie zmieniono schematu żadnej z pięciu baz danych z danymi użytkownika

## Zmiany w 0.8.9

- dodano trwałą pamięć podręczną metadanych ISBN w `${XDG_CACHE_HOME:-~/.cache}/sesyjka/books/`. Ponowne otwarcie formularza z tym samym ISBN nie wykonuje kolejnych zapytań HTTP
- zapamiętywany jest także wynik wyszukiwania okładki, w tym brak obrazu. Ręczny przycisk `Pobierz z ISBN` wymusza ponowne sprawdzenie źródeł internetowych
- dodano wewnętrzny padding po obu stronach dzielonego edytora pozycji RPG, aby formularz i panel ISBN nie stykały się z separatorem ani krawędziami
- pod tytułem aplikacji wyświetlany jest opis `Kolekcja RPG, sesje i gry planszowe` zamiast informacji o użytym toolkicie
- ikona sprawdzania aktualizacji używa `software-update-available-symbolic` z awaryjnym `view-refresh-symbolic`, gdy aktywny motyw ikon nie udostępnia pierwszej nazwy
- nie zmieniono schematu żadnej bazy SQLite

## Zmiany w 0.8.8

- przebudowano wyszukiwanie ISBN. Myślniki i spacje są usuwane, a program próbuje zarówno ISBN-10, jak i ISBN-13
- dodano publiczne API Biblioteki Narodowej jako źródło tytułu, roku wydania i wydawcy, szczególnie dla polskich publikacji
- Google Books nie jest już przeszukiwane wyłącznie zapytaniem `isbn:`. Dodano wyszukiwanie po surowym ISBN oraz awaryjne wyszukiwanie po tytule i wydawcy
- panel ISBN pokazuje teraz także wydawcę. Jeśli odpowiada on istniejącemu rekordowi w `wydawcy.db`, program może wybrać go w formularzu
- pobieranie okładki próbuje kolejnych źródeł zamiast kończyć po pierwszym brakującym obrazie
- dla woluminów Google Books program tworzy dodatkowe adresy front cover na podstawie ID woluminu, również gdy `imageLinks` jest puste
- pozostawiono wcześniejszy układ formularza 60/40, informacyjną cenę online, cache XDG i wykonywanie operacji sieciowych poza głównym wątkiem GTK
- nie zmieniono schematu żadnej bazy SQLite

## Zmiany w 0.8.7

- dodano dzielony formularz pozycji RPG z panelem okładki i metadanych ISBN
- dodano pobieranie tytułu, roku wydania, okładki oraz informacyjnej ceny Google Books
- pobieranie działa w wątku roboczym, a okładki są buforowane w katalogu XDG cache

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
${XDG_CACHE_HOME:-~/.cache}/sesyjka/
```

Pliki baz:

```text
systemy_rpg.db
sesje_rpg.db
gracze.db
wydawcy.db
planszowe.db
```

Stan chmury jest przechowywany osobno:

```text
sync.db
```

Pierwsze cztery pliki zachowują schematy zgodne z projektem `ZuraffPL/sesyjka`. Nowa funkcja planszówek nie dodaje tabel ani kolumn do tych baz. Jest przechowywana wyłącznie w `planszowe.db`.

Import i tryb gościa nadal akceptują zestaw zawierający tylko cztery oryginalne bazy. W takim przypadku zakładka gier planszowych pozostaje pusta. Eksport tworzony przez wersję 0.9.8 zawiera sześć baz danych użytkownika, w tym `planszowe.db` i `zasoby.db`. `sync.db` nie jest eksportowany, ponieważ zawiera stan konkretnego konta i urządzenia.

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

Testy obejmują CRUD sześciu baz domenowych, zgodność zestawu czterech baz projektu źródłowego, walidację sesji, migrację schematu, transfer danych, eksport kalendarza, dynamiczne ceny, statystyki, skrypty instalacyjne, pakowanie Release oraz aktualizator.

## Licencja

Port zachowuje licencję CC BY 4.0 i atrybucję projektu źródłowego. Zobacz `LICENSE` i `NOTICE.md`.
