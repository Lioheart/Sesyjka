# Atrybucja i zakres portu

Ten port GTK4 jest oparty na projekcie Sesyjka autorstwa ZuraffPL:

https://github.com/ZuraffPL/sesyjka

Wersja źródłowa użyta jako punkt odniesienia funkcjonalnego: 0.4.52.

Dystrybucja zachowuje licencję CC BY 4.0 i atrybucję projektu źródłowego. Warstwa Tkinter, CustomTkinter, ttk i tksheet została zastąpiona przez PyGObject, GTK4 oraz Libadwaita. Dodano ścieżki XDG, integrację pulpitu Linuksa, pakiety DEB i RPM, instalator ogólny, aktualizator wydań, natywne selektory plików i testowalną warstwę repozytorium.

Wersja 0.7.0 rozdziela uruchamianie lokalne od instalacji systemowej, dodaje systemowy deinstalator, pakiety DEB i RPM budowane przy publikacji wydania, instalator ogólny dla pozostałych dystrybucji oraz aktualizator oparty na opublikowanych wydaniach GitHub. Zachowuje także eksport baz do folderu, kontrolę importu, backup przed migracją schematu, rotowane logi, wybór grup graczy i rozszerzoną walidację integralności pomiędzy bazami.
