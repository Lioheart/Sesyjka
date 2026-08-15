# Sesyjka Cloud 0.9.6 - konfiguracja Supabase i Discord

Konfigurację wykonuje administrator projektu Sesyjka tylko raz. Użytkownik końcowy loguje się przyciskiem `Zaloguj przez Discord` i nie wykonuje żadnego SQL ani nie konfiguruje Discord Developer Portal.

## 1. Projekt Supabase

Potrzebujesz jednego projektu Supabase. Do aplikacji desktopowej używaj wyłącznie:

- Project URL, np. `https://abcdefghijklmnopqrst.supabase.co`
- Publishable key `sb_publishable_...` albo legacy anon key

Nigdy nie umieszczaj w Sesyjce klucza `service_role` ani secret key.

## 2. Discord OAuth

W Discord Developer Portal utwórz aplikację i przejdź do OAuth2. Jako Redirect URI dodaj dokładnie callback Supabase widoczny w `Authentication -> Providers -> Discord`:

```text
https://<project-ref>.supabase.co/auth/v1/callback
```

Skopiuj Discord Client ID i Client Secret. W Supabase otwórz `Authentication -> Providers -> Discord`, włącz provider, wpisz Client ID i Client Secret, a następnie zapisz ustawienia.

## 3. Redirect z Supabase do aplikacji GTK4

W Supabase otwórz `Authentication -> URL Configuration`. Do listy Redirect URLs dodaj dokładnie:

```text
http://127.0.0.1:8765/auth/callback
```

To nie jest callback, który wpisujesz w Discord Developer Portal. Discord wraca najpierw do Supabase. Dopiero Supabase przekierowuje przeglądarkę do lokalnej Sesyjki.

Sesyjka wiąże lokalny serwer wyłącznie do `127.0.0.1`, więc nie wystawia portu 8765 do sieci LAN. Przepływ używa PKCE z metodą S256.

## 4. Tabela synchronizacji

W Supabase SQL Editor uruchom cały plik:

```text
supabase/schema.sql
```

Skrypt tworzy `public.sesyjka_records`, indeks, trigger `updated_at`, włącza Row Level Security i tworzy polityki dla roli `authenticated`. Użytkownik może odczytać i zmienić wyłącznie rekordy, których `owner_id` odpowiada `auth.uid()`.

Sprawdzenie tabeli:

```sql
select to_regclass('public.sesyjka_records');
```

Poprawny wynik:

```text
public.sesyjka_records
```

Sprawdzenie polityk:

```sql
select policyname, cmd
from pg_policies
where schemaname = 'public'
  and tablename = 'sesyjka_records'
order by policyname;
```

Powinny istnieć polityki SELECT, INSERT, UPDATE i DELETE utworzone przez `schema.sql`.

## 5. Data API

Tabela znajduje się w schemacie `public`. Schemat `public` musi być wystawiony przez Supabase Data API. W standardowym projekcie jest to ustawienie domyślne. Jeżeli Data API zostało ograniczone ręcznie, dodaj `public` do exposed schemas.

Po zmianach schematu można wymusić przeładowanie cache PostgREST:

```sql
NOTIFY pgrst, 'reload schema';
```

## 6. Konfiguracja klienta

Produkcja 0.9.6 ma zapisane w aplikacji:

```text
SUPABASE_URL=https://rjevhlnscdodgoaztxao.supabase.co
SUPABASE_KEY=sb_publishable_AfaZRdfEWMi9QSMOjXgoRA_6zA6W7Yn
```

Publishable key jest publicznym kluczem klienta. Nie umieszczaj w repozytorium `service_role`, secret key, hasła bazy ani Discord Client Secret.

Zwykły użytkownik nie widzi konfiguracji Supabase. Po kliknięciu `Zaloguj przez Discord` aplikacja korzysta z produkcyjnego backendu. Dla developmentu można tymczasowo nadpisać go zmiennymi:

```bash
export SESYJKA_SUPABASE_URL='https://testowy-projekt.supabase.co'
export SESYJKA_SUPABASE_KEY='sb_publishable_...'
./run.sh
```

Po kliknięciu `Zaloguj przez Discord`:

1. Sesyjka tworzy losowy PKCE verifier i challenge.
2. Otwiera `/auth/v1/authorize?provider=discord` w domyślnej przeglądarce.
3. Discord uwierzytelnia użytkownika i wraca do callbacku Supabase.
4. Supabase wraca do `http://127.0.0.1:8765/auth/callback?code=...`.
5. Sesyjka wymienia jednorazowy kod na access token i refresh token.
6. Pierwsze logowanie automatycznie tworzy konto w Supabase Auth.
7. Aplikacja natychmiast uruchamia synchronizację.

## 7. Dane lokalne i offline

Pięć baz domenowych pozostaje bez zmian:

```text
systemy_rpg.db
sesje_rpg.db
gracze.db
wydawcy.db
planszowe.db
```

Dodatkowy `sync.db` przechowuje tylko stan synchronizacji i konflikty. Brak Internetu nie blokuje CRUD. Gdy sieć wróci, automatyczna synchronizacja ponownie wysyła lokalne zmiany.

Token odświeżania jest przechowywany w `${XDG_CONFIG_HOME:-~/.config}/sesyjka/cloud-session.json` z prawami `0600`. Hasło Discord nigdy nie trafia do aplikacji.
