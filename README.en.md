# Sesyjka GTK4 0.8.5

A native Linux application built with Python, GTK4 and Libadwaita. It manages tabletop RPG systems, books, supplements, sessions, players, publishers, board games and card games. The four original SQLite databases remain compatible, while board and card games use a separate fifth database.

Result repository: https://github.com/Lioheart/Sesyjka

Original project and attribution: https://github.com/ZuraffPL/sesyjka

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
