# Audyt zgodności funkcjonalnej z projektem źródłowym

Punktem odniesienia są `CLAUDE.MD` i sekcja funkcjonalności oraz changelogu z README projektu ZuraffPL/sesyjka. Audyt dotyczy podstawowych funkcji użytkowych i zasad integralności danych, nie zgodności piksel w piksel z wersją CustomTkinter dla Windows.

## Funkcje pokryte

| Obszar źródłowy | Stan portu GTK4 0.8.6 |
|---|---|
| Cztery oddzielne bazy SQLite projektu źródłowego | Zachowane bez dodawania tabel planszówkowych: systemy, sesje, gracze i wydawcy |
| Osobna kolekcja planszówek i karcianek | Dodana w niezależnym pliku `planszowe.db`, bez zmiany czterech baz źródłowych |
| Systemy RPG, podręczniki i suplementy | CRUD oraz hierarchia system, grupa organizacyjna i przypisane pozycje |
| Status kolekcji i status gry | Dostępne w formularzu oraz tabeli. Kolorowanie całych wierszy zostało wycofane z powodu ograniczeń i stabilności Gtk.ColumnView |
| Fizyczne, PDF, VTT, język | Dostępne |
| Ceny zakupu i sprzedaży, waluty | Ceny fizyczna, PDF i VTT są warunkowe. Cena łączna jest wyliczana automatycznie. Cena sprzedaży jest widoczna tylko dla `Na sprzedaż` lub `Sprzedane` |
| Rok wydania i ISBN | Dostępne |
| Wydawca pozycji i systemu | Dostępny, z szybkim dodawaniem wydawcy z formularza |
| Sortowanie hierarchii | Sortowanie rodzeństwa bez rozrywania relacji nadrzędnych |
| Sortowanie tabel płaskich | Kliknięcie nagłówka kolumny |
| Wyszukiwanie i filtry | Filtr globalny, filtry każdej kolumny i wyszukiwanie w rozwijanych listach |
| Menu prawego przycisku | Edycja i usuwanie z ikonami symbolicznymi |
| Sesje RPG | Data, system, gracze, MG, GM-less, kampania, jednostrzał, tryb gry, tytuły i notatki. Eksport do iCalendar i CSV kalendarza |
| Grupy graczy | Tagi rozdzielane przecinkami i szybkie zaznaczanie grupy w sesji |
| Blokada sesji bez graczy | Walidacja w formularzu i repozytorium |
| Gracze | CRUD, dane opisowe, grupa, główny użytkownik i ważny gracz |
| Wydawcy | CRUD, kraj, strona WWW i powiązanie z katalogiem |
| Statystyki | Liczniki, zestawienia, wykresy ilości i automatyczne odświeżanie po CRUD. Osobny licznik Planszówki/Karcianki i wykres z podziałem na oba typy |
| Transfer baz | ZIP, folder, XLSX, import ZIP i folderu, backup oraz walidacja |
| Tryb gościa | Połączenia SQLite `mode=ro` i blokada operacji zapisu |
| Motyw i skala tekstu | Jasny i ciemny Adwaita, skala od 80 do 140 procent |
| Pomoc i historia zmian | Dostępne z nagłówka i dialogu O programie |
| Logowanie diagnostyczne | Rotowany log w katalogu XDG state |
| Migracja starszego schematu | Brakujące tabele i kolumny są tworzone po wykonaniu kopii zapasowej |
| Integralność pomiędzy bazami | Walidacja ID w Pythonie przed zapisem i blokada usuwania rekordów powiązanych |
| Integralność wewnątrz bazy | `PRAGMA foreign_keys = ON` dla każdego połączenia |

## Różnice i funkcje częściowe

| Funkcja wersji Windows | Stan portu GTK4 |
|---|---|
| Splash screen | Niezaimplementowany. Nie wpływa na zarządzanie danymi |
| Graficzny kalendarz dat | Zastąpiony walidowanym polem `RRRR-MM-DD` |
| Wykresy Matplotlib | Zastąpione natywnymi, dostępnymi wykresami ilości GTK4 |
| Zapamiętywanie szerokości każdej kolumny | Kolumny można zmieniać, ale ich szerokości nie są jeszcze zapisywane |
| Reguły kolorowania wierszy systemów | Zaimplementowane kolory Adwaita dla statusów Grane, Nie grane, Planowane i Ukończone |
| Wielokrotny selektor typów suplementów | Pole podgrupy jest elastycznym tekstem i może przechowywać kilka tagów rozdzielonych przecinkami |
| Osobny ekran historii uczestnictwa gracza | Udział graczy jest dostępny w statystykach, bez osobnego widoku historii |

## Wnioski

Wersja 0.8.6 usuwa nieobsługiwane manipulowanie prywatnymi widgetami wierszy Gtk.ColumnView. Port zachowuje podstawowy przepływ pracy programu źródłowego: katalog kolekcji RPG, sesje, gracze, wydawcy, statystyki, filtry, transfer i bezpieczeństwo czterech baz. Wersja 0.8.6 obejmuje kolekcję planszówek i karcianek jako niezależne rozszerzenie w piątym pliku. Nie zmienia schematów czterech baz projektu źródłowego.
