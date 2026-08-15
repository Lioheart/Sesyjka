# Sesyjka GTK4 0.9.2

A native Linux application built with Python, GTK4 and Libadwaita. It manages tabletop RPG systems, books, supplements, sessions, players, publishers, board games and card games. The four original SQLite databases remain compatible, while board and card games use a separate fifth database.

Result repository: https://github.com/Lioheart/Sesyjka

Original project and attribution: https://github.com/ZuraffPL/sesyjka

## Sesyjka Cloud 0.9.2

Version 0.9.2 uses Discord OAuth for the optional offline-first cloud synchronization. Existing SQLite databases remain the local source of truth and keep their current schemas. A separate `sync.db` stores synchronization mappings, device state and unresolved conflicts.

The cloud backend uses Supabase Auth and the Supabase Data REST API. The production Project URL and publishable key are bundled with the application, so end users only need to choose Discord login. Run `supabase/schema.sql` once on the production backend. Never use a secret/service-role key in the desktop client.

The application signs users in through Discord OAuth in the default browser, refreshes the resulting Supabase session, synchronizes manually or automatically, continues working offline, and explicitly resolves records that changed both locally and remotely. The header shows the current cloud state and conflict count.

See `supabase/README.md` for setup instructions. Discord passwords never reach Sesyjka. Authentication takes place in the default browser using OAuth PKCE. The refresh token is stored in the user configuration directory with file mode `0600`, but version 0.9.2 does not encrypt that file itself.

## Changes in 0.9.2

- bundled the production Supabase URL and publishable key and removed backend configuration fields from the GUI
- retained environment-variable overrides for development and testing
- added a Calendar menu for the selected RPG session
- Google Calendar opens a pre-filled browser event form
- Apple/iCloud handoff writes a single-event ICS file to Downloads and opens iCloud Calendar
- original user database schemas remain unchanged

## Changes in 0.9.1

- replaced email/password Cloud login with Discord OAuth
- added OAuth Authorization Code with PKCE S256 and a loopback-only callback at `127.0.0.1:8765`
- the first Discord login creates the Supabase Auth user automatically
- successful login immediately starts cloud synchronization

## Changes in 0.9.0

- added a separate `sync.db` without altering the five user-data database schemas
- added Supabase Auth sign-up, sign-in, session refresh and sign-out
- added offline-first local-to-cloud and cloud-to-local synchronization
- added startup, periodic, debounced-after-CRUD and manual synchronization
- added a visible Cloud status control in the application header
- added explicit local/cloud conflict comparison and resolution
- cloud deletions use tombstones so they can propagate to other devices
- added `supabase/schema.sql` with Row Level Security policies scoped to `auth.uid()`
- increased the main application title size

## Changes in 0.8.9

- ISBN metadata is now cached persistently under the XDG cache directory, so reopening an item does not repeat network requests
- failed cover lookups are cached too. The `Pobierz z ISBN` button explicitly forces a refresh
- the split RPG item editor now has consistent inner padding around both panes
- the window subtitle now describes the application instead of exposing toolkit names
- update checks use `software-update-available-symbolic` with `view-refresh-symbolic` as a theme fallback
- SQLite schemas remain unchanged

## Changes in 0.8.8

- ISBN lookup now normalizes separators and searches both ISBN-10 and ISBN-13 variants.
- Added the Polish National Library public API as a metadata source for title, publication year and publisher.
- Google Books lookup now falls back from `isbn:` to the raw identifier and then to title/publisher searches.
- The ISBN preview displays publisher metadata and can match an existing publisher record.
- Cover download tries multiple candidates and can request a Google Books front cover directly from the volume ID when `imageLinks` is missing.
- SQLite schemas remain unchanged.

## Changes in 0.8.6

- RPG item types are now limited to `Main Rulebook`, `Supplement`, `Other` and the database value `Grupa`
- only records whose stored type is `Grupa` can be selected in the renamed group field
- the group selector is restricted to the currently selected RPG system
- group records cannot be nested, converted or moved to another system while they contain items
- the existing `system_glowny_id` column and the original database schema remain unchanged
- collection-status row coloring remains disabled. Tables use the native Adwaita background and selection highlight only
- the database action uses `document-save-symbolic`, while update checks use `software-update-available`

## Changes in 0.8.5

- removed unsupported traversal and mutation of private `Gtk.ColumnView` row widgets that could trigger GTK accessibility assertions and segmentation faults
- temporarily removed collection-status row coloring until the table is migrated to a public whole-row widget API
- selection styling now uses only the supported `row:selected` CSS state
- light and dark appearance remains controlled through `Adw.StyleManager`

## Changes in 0.8.4

- the game-system editor now exposes only the name and notes fields
- board and card games select publishers from `wydawcy.db` and can create a publisher without closing the form
- `planszowe.db` stores `wydawca_id` while retaining the publisher name for backward compatibility
- legacy publisher names are linked automatically when an exact case-insensitive match exists
- board-game notes were removed from the editor without dropping the legacy database column
- publisher websites are clickable in the table and open in the default browser

## Changes in 0.8.3

- collection-status classes are applied to the actual internal row widget instead of cell containers
- alternating stripes use the GTK `row:nth-child(even)` selector
- supplement subgroup values are stored with the ` | ` separator
- language is selected from PL, ENG, DE, FR, ES, IT or Other
- ISBN-10 and ISBN-13 check digits are validated, while invalid values can still be saved after a warning
- the database manager button uses the `database` icon

## Changes in 0.8.2

- introduced collection-status backgrounds, striped tables and multiple supplement subgroup selection
- the purchase currency field suggests the common PLN, USD, EUR and GBP codes

## Release packages

Every published GitHub Release triggers `.github/workflows/release.yml`. A release tag must use `vX.Y.Z` and match the versions in `pyproject.toml` and `sesyjka/__init__.py`.

The workflow attaches:

- `sesyjka_X.Y.Z_all.deb` for Ubuntu and Debian based systems
- `sesyjka-X.Y.Z-1.fc*.noarch.rpm` for Fedora
- `sesyjka-X.Y.Z-linux-installer.tar.gz` and `.zip` for other distributions
- `SHA256SUMS` for update verification

Ubuntu installation:

```bash
sudo apt install ./sesyjka_X.Y.Z_all.deb
```

Fedora installation:

```bash
sudo dnf install ./sesyjka-X.Y.Z-1.fc*.noarch.rpm
```

Generic installation:

```bash
./install-linux.sh
```

## Updates

The application checks the latest stable GitHub Release at startup, at most once every six hours. A manual check is available from the header and the About window.

For DEB, RPM and generic system installations, the updater selects the matching release asset, verifies SHA-256, requests administrator authorisation through Polkit and invokes the appropriate installer. A source checkout started with `run.sh` is never overwritten automatically and instead opens the release page.

## Local execution

`run.sh` only starts the current source tree. It does not install, copy or update system files.

Ubuntu dependencies:

```bash
sudo apt install python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 python3-openpyxl
./run.sh
```

Fedora dependencies:

```bash
sudo dnf install python3 python3-gobject gtk4 libadwaita python3-openpyxl
./run.sh
```

## Tests

```bash
python3 -m compileall -q sesyjka tests
python3 -m unittest discover -s tests -v
bash -n run.sh install-linux.sh uninstall-linux.sh packaging/*.sh
```

## License

The port retains the CC BY 4.0 license and attribution of the original project. See `LICENSE` and `NOTICE.md`.
