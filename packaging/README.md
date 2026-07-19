# Pakowanie wydań

Publikacja GitHub Release uruchamia `.github/workflows/release.yml`. Workflow sprawdza zgodność tagu `vX.Y.Z` z `pyproject.toml`, uruchamia testy i dołącza do wydania:

- `sesyjka_X.Y.Z_all.deb` dla Ubuntu i innych systemów Debianowych
- `sesyjka-X.Y.Z-1.fc*.noarch.rpm` dla Fedory
- `sesyjka-X.Y.Z-linux-installer.tar.gz` oraz `.zip` dla pozostałych dystrybucji
- `SHA256SUMS` używany przez wbudowany aktualizator

Lokalne budowanie:

```bash
./packaging/build-deb.sh
./packaging/build-rpm.sh
./packaging/build-generic.sh
```

Pakiety DEB i RPM instalują kod w `/usr/share/sesyjka` i program uruchamiający w `/usr/bin/sesyjka`. Instalator ogólny zachowuje dotychczasowy układ `/opt/sesyjka` i `/usr/local/bin/sesyjka`.
