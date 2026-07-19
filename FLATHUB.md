# Flatpak i zgłoszenie do Flathub

Identyfikator aplikacji: `io.github.zuraffpl.Sesyjka`.

Lokalny manifest używa `org.gnome.Platform//50` i `org.gnome.Sdk//50`. Jawne uprawnienia wykonawcze to Wayland, awaryjny X11, IPC oraz DRI. Manifest nie przyznaje dostępu `--filesystem=home` ani `--filesystem=host`.

## Budowanie lokalne

```bash
flatpak remote-add --user --if-not-exists flathub \
  https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak install --user flathub \
  org.flatpak.Builder org.gnome.Platform//50 org.gnome.Sdk//50
./flatpak/build-local.sh
flatpak run io.github.zuraffpl.Sesyjka
```

Dane Flatpaka są zapisywane w prywatnych katalogach aplikacji:

```text
~/.var/app/io.github.zuraffpl.Sesyjka/data/sesyjka/
~/.var/app/io.github.zuraffpl.Sesyjka/config/sesyjka/
~/.var/app/io.github.zuraffpl.Sesyjka/state/sesyjka/
```

Odinstalowanie z zachowaniem danych:

```bash
flatpak uninstall --user io.github.zuraffpl.Sesyjka
```

Odinstalowanie wraz z danymi:

```bash
flatpak uninstall --user --delete-data io.github.zuraffpl.Sesyjka
```

## Walidacja

Po zainstalowaniu `org.flatpak.Builder`:

```bash
flatpak run --command=flatpak-builder-lint org.flatpak.Builder \
  manifest flatpak/io.github.zuraffpl.Sesyjka.yml
```

Pełna kontrola repozytorium:

```bash
rm -rf repo build-dir
flatpak run --command=flatpak-builder org.flatpak.Builder \
  --repo=repo --force-clean build-dir flatpak/io.github.zuraffpl.Sesyjka.yml
flatpak run --command=flatpak-builder-lint org.flatpak.Builder repo repo
```

## Wydanie źródłowe

Manifest zgłoszeniowy Flathub nie powinien używać lokalnego źródła `type: dir`. Powinien pobierać niezmienne archiwum wydania, przypięte sumą SHA-256. Dostarczony zestaw zgłoszeniowy zawiera taki manifest dla tagu `v0.6.4` i pliku:

```text
sesyjka-gtk4-0.6.4-source.tar.gz
```

Przed otwarciem pull requestu należy opublikować bez zmiany bajtów dokładnie to archiwum, do którego odnosi się manifest.

## Zrzuty ekranu

W repozytorium wydania musi istnieć katalog `screenshots/` z plikami `image.png` oraz `image2.png` do `image11.png`. MetaInfo używa 10 z nich i odwołuje się do tagu `v0.6.4`, a nie do zmiennej gałęzi `main`.

Zrzuty przedstawiają polski interfejs. Wszystkie powinny być oznaczone jako `xml:lang="pl"`. Flathub zaleca od 6 do 10 zrzutów dla dużej aplikacji i wymaga co najmniej jednego zrzutu angielskiego dla standardowego zgłoszenia.

## Ograniczenie publikacyjne

Interfejs Sesyjki 0.6.4 jest polskojęzyczny. Flathub wymaga kompletnej lokalizacji angielskiej wszystkich treści użytkowych, ale dopuszcza wyjątki dla nowych zgłoszeń autorów nieanglojęzycznych. Pakiet jest przygotowany technicznie do budowania i recenzji, jednak przyjęcie wymaga jednego z dwóch rozwiązań:

1. Dodania pełnej, ręcznie sprawdzonej lokalizacji angielskiej i co najmniej jednego angielskiego zrzutu.
2. Uzyskania wyjątku podczas recenzji zgłoszenia.

Nie należy opisywać tego pakietu jako bezwarunkowo zaakceptowanego przez Flathub przed zakończeniem recenzji.
