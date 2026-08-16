# Sesyjka GTK4 0.9.17

A native Linux application built with Python, GTK4 and Libadwaita. It manages tabletop RPG systems, books, supplements, sessions, players, publishers, board games and card games. The four original SQLite databases remain compatible, while board and card games use a separate fifth database.

Result repository: https://github.com/Lioheart/Sesyjka

Original project and attribution: https://github.com/ZuraffPL/sesyjka

## Sesyjka Cloud 0.9.17

Version 0.9.17 uses Discord OAuth for the optional offline-first cloud synchronization. Existing SQLite databases remain the local source of truth and keep their current schemas. A separate `sync.db` stores synchronization mappings, device state and unresolved conflicts.

The cloud backend uses Supabase Auth and the Supabase Data REST API. The production Project URL and publishable key are bundled with the application, so end users only need to choose Discord login. Run `supabase/schema.sql` once on the production backend. Never use a secret/service-role key in the desktop client.

The application signs users in through Discord OAuth in the default browser, refreshes the resulting Supabase session, and synchronizes manually or on a configurable periodic interval. A local edit never starts network synchronization immediately. It is committed to SQLite first and queued in `sync.db`. Subsequent passes scan only locally changed databases and request remote rows from the stored `updated_at` cursor. If the same record changed on both sides, the current local SQLite row wins. Legacy unresolved conflicts remain visible for compatibility.

See `supabase/README.md` for setup instructions. Discord passwords never reach Sesyjka. Authentication takes place in the default browser using OAuth PKCE. The refresh token is stored in the user configuration directory with file mode `0600`, but version 0.9.17 does not encrypt that file itself.


## Digital resources in 0.9.4

Version 0.9.4 adds a separate `zasoby.db` library for PDFs, VTT content and web resources. Files are not copied into the application. Logical storage roots represent local disks, NAS shares or USB devices, while resource locations store a stable storage UUID and a relative path. Device-specific mount-point mappings are not synchronized. Resources and logical locations can be synchronized through Sesyjka Cloud.

The PDF scanner recursively indexes files, calculates SHA-256 and only auto-links a file to an RPG item at high confidence. The DriveThruRPG integration is experimental: an Application Key with My Library Access can import purchase/file metadata and product links without automatically downloading large PDFs. The key stays local with mode `0600`.

## Changes in 0.9.17

- `Group` RPG items now contain and edit only name, type and RPG system assignment
- on first 0.9.17 startup, legacy metadata stored on group rows is removed from `systemy_rpg.db` after an automatic safety backup
- Cloud sync sanitizes legacy group payloads so older remote data cannot restore removed metadata
- the collection-value chart now aggregates RPG item value by RPG system rather than by individual title

## Changes in 0.9.16

- all summary cards, including collection value, stay in a single row
- Statistics now has two subtabs: `Charts` and `Sessions and players`, keeping the pie chart fully visible below the cards
- the collection-value card opens a value-by-title chart with currency-aware formatting and no cross-currency summation
- present `Physical`, `PDF` and `VTT` format markers use a stronger filled success indicator for better contrast

## Changes in 0.9.15

- fixed pie chart rendering in Statistics. The previous implementation used Cairo method names that do not exist in the Python API, so the legend was visible while the chart itself was blank
- RPG system group counts now use the intended Polish forms for one, two to four, and five or more items
- the `Physical`, `PDF` and `VTT` columns in the RPG Systems table now use graphical present/absent indicators instead of textual `Tak` values

## Changes in 0.9.14

- digital resource locations beginning with `https://` or `http://` are displayed as clickable links in the editor and open in the default browser
- local, NAS and USB file locations remain plain text

## Changes in 0.9.12

- linking a PDF digital resource to an RPG item automatically enables the PDF format flag on that item
- linking a VTT resource automatically enables VTT and uses a recognized platform name when available, without overwriting an existing manually entered VTT platform
- the same format propagation is applied to auto-linked local PDF scans and DriveThruRPG imports
- table refreshes after CRUD operations preserve the selected row, scroll position and expanded group state instead of jumping back to the top
- user databases remain under `${XDG_DATA_HOME:-~/.local/share}/sesyjka/` by default and can be redirected with `SESYJKA_DATA_DIR`

## Changes in 0.9.11

- automatic cloud synchronization is periodic rather than triggered after each local edit
- `sync.db` records which local databases are dirty, while file fingerprints detect edits made while Sesyjka was closed
- remote synchronization uses an `updated_at` cursor and unchanged local records are not uploaded again
- Supabase reads are paginated so full synchronization and large remote deltas are not limited to the first result page
- when both sides changed the same record, the local SQLite value wins deterministically
- new installations default to a 15 minute interval, configurable from 1 minute to 24 hours
## Changes in 0.9.10

- cloud synchronization now creates a coherent local safety snapshot before applying remote database changes and automatically restores local databases plus `sync.db` if a synchronization pass fails
- a physically missing Supabase row is no longer treated as a deletion. Local deletion is propagated only from an explicit `deleted=true` tombstone
- RPG self-references are ordered by the actual `system_glowny_id` dependency so parents are created first and children are deleted first
- foreign-key failures identify the affected cloud record and trigger rollback instead of leaving earlier databases partially modified
- a conservative recovery path restores `wydawcy.db` from the newest compatible backup when the current publisher table is empty but other local records still reference publisher IDs
- the 0.9.9 DriveThruRPG table behavior remains unchanged: the resource name is the product title and a separate file-name column shows the specific download

## Changes in 0.9.9

- restored the DriveThruRPG product title as the main resource name, so all downloads belonging to a product continue to show the product name
- added a separate `File name` column to the digital-resources table. It shows the friendly DriveThruRPG file title when available, otherwise the technical filename
- the technical filename remains stored separately for format detection and local-file metadata
- `zasoby.db` is migrated automatically with a backward-compatible file-title field. Re-synchronizing DriveThruRPG fills it and restores product names on records imported by 0.9.8

## Changes in 0.9.8

- when a DriveThruRPG product contains multiple files, each imported resource now uses the specific file title instead of repeating the product title
- a friendly file title from the API is preferred. If unavailable, the filename stem is used
- the product title is retained separately for automatic matching to the RPG collection, so ancillary files remain linked to the correct product
- re-synchronizing updates resources already imported by 0.9.7 because DriveThruRPG external identifiers are unchanged
- no user database schema changes

## Changes in 0.9.7

- fixed DriveThruRPG library authorization to match the current official SDK implementation. The JWT is sent first as the raw `Authorization` header value, without a `Bearer` prefix
- kept a single `Authorization: Bearer <token>` compatibility retry for backends following the older OpenAPI description
- `POST /auth_key` now sends an empty JSON object `{}` while passing the Application Key as a query parameter, matching the current SDK
- 401 responses from `auth_key` are reported as Application Key failures, while 401 responses from `order_products` are reported as JWT session failures
- added regression tests for raw JWT authorization, Bearer fallback, authentication request body and 401 error classification
- no user database schema changes

## Changes in 0.9.6

- fixed DriveThruRPG HTTP transport by decoding `gzip`/`deflate` responses while requesting `identity` by default
- fixed authenticated library calls to use the required `Authorization: Bearer <token>` header
- aligned `order_products` parsing with the paginated JSON:API response containing `links`, `meta`, `data` and `included`
- publisher names are also resolved from included Publisher objects through `royaltyPublisherId`
- kept the older direct-list parser as a compatibility fallback
- kept the current My Library URL at `https://www.drivethrurpg.com/en/mylibrary`
- no user database schema changes

## Changes in 0.9.4

- Added `zasoby.db`, digital-resource storage roots, PDF scanning and multiple locations.
- Added experimental DriveThruRPG library metadata import.
- Digital resources and logical locations sync through Cloud, while device path mappings remain local.
- The original four upstream database schemas remain unchanged.

## Changes in 0.9.3

- fixed the RPM source tree, which omitted `supabase/` and caused `%check` to fail with `FileNotFoundError: supabase/schema.sql`
- centralized release-source staging for the generic installer and RPM in `stage_release_source`
- the RPM now installs `supabase/schema.sql` and `supabase/README.md` as backend-administrator documentation
- added a regression test that verifies the Cloud setup files are present in RPM sources
- no user database schema or synchronization protocol changes

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
