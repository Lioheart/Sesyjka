# Sesyjka GTK4 0.6.4

Sesyjka is a native GTK4 and Libadwaita application for Linux. It manages tabletop RPG systems, hierarchical book collections, sessions, players, publishers and collection statistics while retaining the four SQLite database files used by the upstream project.

## Core features

The application provides hierarchical system, core-book and supplement management, sortable and filterable tables, right-click editing and deletion, session notes, player groups, publisher assignment, collection prices, currencies, VTT data, release years and ISBN values. Sessions require at least one valid player and use the game-system catalogue rather than book titles.

Database transfer includes ZIP export, folder export, XLSX export, validated ZIP or folder import with backup, and a read-only guest mode. Cross-database identifiers are validated in Python. Existing databases are backed up before schema migration.

The interface provides forced light and dark Adwaita styles, text scaling, help, release history, quantity charts and automatic statistics refresh after data changes.

## Local execution

`run.sh` only starts the source tree. It does not install desktop files or copy application files.

```bash
./run.sh
```

## System installation

```bash
./install-linux.sh
sesyjka
```

The default installation paths are `/opt/sesyjka`, `/usr/local/bin/sesyjka` and `/usr/local/share`.

System removal while retaining user data:

```bash
sudo /opt/sesyjka/uninstall-linux.sh
```

Removal including the current user's data:

```bash
sudo /opt/sesyjka/uninstall-linux.sh --purge-data
```

## Flatpak

```bash
flatpak install --user flathub \
  org.flatpak.Builder org.gnome.Platform//50 org.gnome.Sdk//50
./flatpak/build-local.sh
flatpak run io.github.zuraffpl.Sesyjka
```

The sandbox does not request unrestricted home-directory access. File import and export use GTK's native file selection and desktop portals.

## Flathub status

The manifest, MetaInfo, desktop file, icons, pinned Python dependencies and release screenshot set are prepared for a Flathub submission. The user interface is currently available in Polish. Flathub requires a complete English localisation for new submissions unless an exception is accepted, so publication is not guaranteed until that policy requirement is resolved.

## Tests

```bash
python3 -m compileall -q sesyjka tests
python3 -m unittest discover -s tests -v
```

## License

The port retains the upstream CC BY 4.0 license and attribution. See `LICENSE` and `NOTICE.md`.
