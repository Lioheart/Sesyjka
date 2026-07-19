# Sesyjka GTK4 0.8.1

A native Linux application built with Python, GTK4 and Libadwaita. It manages tabletop RPG systems, books, supplements, sessions, players, publishers and four compatible SQLite databases.

Result repository: https://github.com/Lioheart/Sesyjka

Original project and attribution: https://github.com/ZuraffPL/sesyjka

## Changes in 0.8.1

RPG rows are now colored by collection status. Database import uses a semantic confirmation action, the header database button uses a storage icon, statistics include the summed purchase value grouped by currency, and the two summary tables have a visible gap and separator.

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
