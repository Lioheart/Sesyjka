from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from . import APP_ID, APP_NAME, APP_VERSION, UPDATE_REPOSITORY
from .config import load_settings, migrate_legacy_databases, save_settings
from .database_manager import DatabaseManager
from .dialogs import ModalWindow, info
from .pages import BoardGamesPage, PlayersPage, PublishersPage, SessionsPage, StatisticsPage, SystemsPage
from .repository import Repository
from .transfer import TransferWindow
from .updater import (
    LatestRelease,
    detect_install_channel,
    download_and_install,
    fetch_latest_release,
    is_newer_version,
    release_page_url,
)
from .widgets import set_css

LOG = logging.getLogger(__name__)

BASE_CSS = """
.app-background,
.app-content,
.page-stack,
.content-page {
  background-color: @window_bg_color;
  color: @window_fg_color;
}
.navigation-strip {
  margin: 12px 12px 0 12px;
  padding: 6px;
  border: 1px solid alpha(@window_fg_color, 0.12);
  border-radius: 12px;
  background-color: @window_bg_color;
}
.data-table-shell {
  border: 1px solid alpha(@window_fg_color, 0.16);
  border-radius: 10px;
  background-color: @view_bg_color;
}
.data-table-scroller,
.data-table {
  background-color: @view_bg_color;
  color: @view_fg_color;
}
.data-table header {
  font-weight: 700;
}
.table-cell {
  padding: 6px 8px;
  border-radius: 0;
  background: none;
}
.table-link {
  padding: 0;
  min-height: 0;
}
.data-table > listview > row {
  background-color: @view_bg_color;
}
.data-table > listview > row > cell {
  background: transparent;
}
.data-table > listview > row:selected {
  background-color: alpha(@accent_color, 0.16);
  box-shadow: inset 0 0 0 2px @accent_color;
}
.stat-card {
  min-width: 130px;
  padding: 16px;
  border: 1px solid alpha(@window_fg_color, 0.14);
  border-radius: 12px;
  background-color: @card_bg_color;
  color: @card_fg_color;
}
.stat-card-button {
  padding: 0;
}
.stat-card-button .stat-card {
  min-width: 130px;
}

.chart-shell {
  padding: 12px;
  border: 1px solid alpha(@window_fg_color, 0.14);
  border-radius: 12px;
  background-color: @card_bg_color;
  color: @card_fg_color;
}
.chart-row {
  padding: 4px 0;
}
.chart-count {
  font-weight: 700;
  min-width: 3em;
}
.context-menu-popover button {
  min-width: 150px;
}
.context-menu-content {
  min-width: 150px;
}
.context-menu-content image {
  min-width: 18px;
}
.statistics-section-separator {
  min-height: 2px;
  margin-top: 8px;
  margin-bottom: 8px;
  background-color: alpha(@window_fg_color, 0.28);
}

.guest-banner {
  padding: 8px 14px;
  background-color: #9a3412;
  color: white;
  font-weight: 700;
}
.error {
  color: #c01c28;
}

.supplement-type-list {
  padding: 10px 12px;
  border: 1px solid alpha(@window_fg_color, 0.14);
  border-radius: 10px;
  background-color: @view_bg_color;
}
.statistics-table-separator {
  min-width: 1px;
  margin-left: 6px;
  margin-right: 6px;
  background-color: alpha(@window_fg_color, 0.22);
}
"""


class SesyjkaWindow(Adw.ApplicationWindow):
    def __init__(self, application: Adw.Application, databases: DatabaseManager) -> None:
        self.settings_data = load_settings()
        super().__init__(application=application, title=f"{APP_NAME} {APP_VERSION}")
        self._base_css_provider = set_css(BASE_CSS)
        self.set_default_size(
            int(self.settings_data.get("width", 1280)),
            int(self.settings_data.get("height", 800)),
        )
        if self.settings_data.get("maximized"):
            self.maximize()
        self.databases = databases
        self.repository = Repository(databases)
        self._font_provider = None
        self.style_manager = Adw.StyleManager.get_default()
        self._update_check_in_progress = False
        self.connect("close-request", self.on_close_request)
        self.set_icon_name(APP_ID)

        self.header = Adw.HeaderBar()
        if hasattr(Adw, "WindowTitle"):
            title = Adw.WindowTitle(title=APP_NAME, subtitle="GTK4 i Libadwaita")
        else:
            title = Gtk.Label(label=APP_NAME)
            title.add_css_class("title")
        self.header.set_title_widget(title)

        transfer_button = Gtk.Button.new_from_icon_name("document-save-symbolic")
        transfer_button.set_tooltip_text("Bazy danych")
        transfer_button.connect("clicked", lambda _button: self.show_transfer())
        self.header.pack_start(transfer_button)

        font_button = Gtk.MenuButton()
        font_button.set_icon_name("preferences-desktop-font-symbolic")
        font_button.set_tooltip_text("Rozmiar tekstu")
        font_popover = Gtk.Popover()
        font_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        font_box.set_margin_top(12)
        font_box.set_margin_bottom(12)
        font_box.set_margin_start(12)
        font_box.set_margin_end(12)
        font_box.append(Gtk.Label(label="Skala tekstu"))
        self.font_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.8, 1.4, 0.1)
        self.font_scale.set_size_request(220, -1)
        self.font_scale.set_value(float(self.settings_data.get("font_scale", 1.0)))
        self.font_scale.set_digits(1)
        self.font_scale.add_mark(1.0, Gtk.PositionType.BOTTOM, "100%")
        self.font_scale.connect("value-changed", self.on_font_scale_changed)
        font_box.append(self.font_scale)
        font_popover.set_child(font_box)
        font_button.set_popover(font_popover)
        self.header.pack_start(font_button)

        self.dark_switch = Gtk.Switch()
        self.dark_switch.set_valign(Gtk.Align.CENTER)
        self.dark_switch.set_tooltip_text("Przełącz jasne i ciemne tło Adwaita")
        self.dark_switch.set_active(bool(self.settings_data.get("dark_mode", False)))
        self.dark_switch.connect("notify::active", self.on_dark_mode_changed)
        theme_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.theme_icon = Gtk.Image.new_from_icon_name("weather-clear-symbolic")
        self.theme_icon.set_tooltip_text("Motyw jasny lub ciemny")
        theme_box.append(self.theme_icon)
        theme_box.append(self.dark_switch)
        self.header.pack_end(theme_box)

        self.update_button = Gtk.Button.new_from_icon_name("software-update-available")
        self.update_button.set_tooltip_text("Sprawdź aktualizacje")
        self.update_button.connect("clicked", lambda _button: self.check_for_updates(manual=True))
        self.header.pack_end(self.update_button)

        about_button = Gtk.Button.new_from_icon_name("help-about-symbolic")
        about_button.set_tooltip_text("O programie")
        about_button.connect("clicked", lambda _button: self.show_about())
        self.header.pack_end(about_button)

        help_button = Gtk.Button.new_from_icon_name("help-browser-symbolic")
        help_button.set_tooltip_text("Instrukcja obsługi")
        help_button.connect("clicked", lambda _button: self.show_help())
        self.header.pack_end(help_button)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        root.add_css_class("app-background")
        root.add_css_class("app-content")
        root.set_hexpand(True)
        root.set_vexpand(True)

        self.guest_banner = Gtk.Label(xalign=0.0)
        self.guest_banner.add_css_class("guest-banner")
        self.guest_banner.set_visible(False)
        root.append(self.guest_banner)

        navigation = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        navigation.set_hexpand(True)
        navigation.set_vexpand(True)
        switcher_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        switcher_box.add_css_class("navigation-strip")
        switcher_box.set_halign(Gtk.Align.CENTER)
        switcher = Gtk.StackSwitcher()
        switcher.set_halign(Gtk.Align.CENTER)
        switcher_box.append(switcher)
        navigation.append(switcher_box)

        self.stack = Gtk.Stack()
        self.stack.add_css_class("page-stack")
        self.stack.set_hexpand(True)
        self.stack.set_vexpand(True)
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        switcher.set_stack(self.stack)
        navigation.append(self.stack)
        root.append(navigation)

        self.pages = {
            "systems": SystemsPage(self, self.repository),
            "sessions": SessionsPage(self, self.repository),
            "players": PlayersPage(self, self.repository),
            "publishers": PublishersPage(self, self.repository),
            "board_games": BoardGamesPage(self, self.repository),
            "statistics": StatisticsPage(self, self.repository),
        }
        self.stack.add_titled(self.pages["systems"], "systems", "Systemy RPG")
        self.stack.add_titled(self.pages["sessions"], "sessions", "Sesje RPG")
        self.stack.add_titled(self.pages["players"], "players", "Gracze")
        self.stack.add_titled(self.pages["publishers"], "publishers", "Wydawcy")
        self.stack.add_titled(self.pages["board_games"], "board_games", "Gry planszowe")
        self.stack.add_titled(self.pages["statistics"], "statistics", "Statystyki")
        self.stack.connect("notify::visible-child-name", lambda *_args: self.refresh_visible_page())
        for page in self.pages.values():
            if hasattr(page, "on_data_changed"):
                page.on_data_changed = self.refresh_dependent_pages

        if hasattr(Adw, "ToolbarView"):
            toolbar_view = Adw.ToolbarView()
            toolbar_view.add_css_class("app-background")
            toolbar_view.add_top_bar(self.header)
            toolbar_view.set_content(root)
            self.set_content(toolbar_view)
        else:
            shell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            shell.add_css_class("app-background")
            shell.append(self.header)
            shell.append(root)
            self.set_content(shell)

        self.apply_dark_mode(self.dark_switch.get_active())
        self.apply_font_scale(float(self.settings_data.get("font_scale", 1.0)))
        self.update_guest_state()
        self.refresh_all()
        GLib.timeout_add_seconds(4, self._startup_update_check)

    def apply_dark_mode(self, enabled: bool) -> None:
        # Przełącznik ma dwa jednoznaczne stany. Wyłączony zawsze wymusza jasne
        # tło, a włączony zawsze wymusza ciemne tło, niezależnie od motywu systemu.
        scheme = Adw.ColorScheme.FORCE_DARK if enabled else Adw.ColorScheme.FORCE_LIGHT
        self.style_manager.set_color_scheme(scheme)
        self.theme_icon.set_from_icon_name(
            "weather-clear-night-symbolic" if enabled else "weather-clear-symbolic"
        )
        self.dark_switch.set_tooltip_text(
            "Przełącz na jasne tło" if enabled else "Przełącz na ciemne tło"
        )

    def on_dark_mode_changed(self, switch: Gtk.Switch, _param: object) -> None:
        self.apply_dark_mode(switch.get_active())

    def apply_font_scale(self, scale: float) -> None:
        scale = min(1.4, max(0.8, scale))
        display = Gdk.Display.get_default()
        if display is not None and self._font_provider is not None:
            Gtk.StyleContext.remove_provider_for_display(display, self._font_provider)
        size = round(14 * scale, 1)
        self._font_provider = set_css(f"* {{ font-size: {size}px; }}")

    def on_font_scale_changed(self, scale: Gtk.Scale) -> None:
        value = round(float(scale.get_value()), 1)
        self.settings_data["font_scale"] = value
        self.apply_font_scale(value)

    def refresh_all(self) -> None:
        for page in self.pages.values():
            page.refresh()

    def refresh_visible_page(self) -> None:
        child = self.stack.get_visible_child()
        if child is not None and hasattr(child, "refresh"):
            child.refresh()

    def refresh_dependent_pages(self) -> None:
        self.pages["statistics"].refresh()
        visible = self.stack.get_visible_child()
        for key in ("systems", "sessions", "players", "publishers", "board_games"):
            page = self.pages[key]
            if page is not visible:
                page.refresh()

    def update_guest_state(self) -> None:
        guest = self.databases.guest_mode
        self.guest_banner.set_visible(guest)
        if guest:
            self.guest_banner.set_text(f"TRYB GOŚCIA. Dane tylko do odczytu: {self.databases.active_root}")
        for page in self.pages.values():
            page.set_read_only(guest)
        self.refresh_all()

    def _current_settings(self) -> dict[str, object]:
        settings: dict[str, object] = dict(self.settings_data)
        settings.update(
            {
                "dark_mode": self.dark_switch.get_active(),
                "font_scale": round(float(self.font_scale.get_value()), 1),
                "width": max(self.get_default_size()[0], 900),
                "height": max(self.get_default_size()[1], 650),
                "maximized": self.is_maximized(),
            }
        )
        return settings

    def _save_current_settings(self) -> None:
        self.settings_data = self._current_settings()
        try:
            save_settings(self.settings_data)
        except OSError:
            LOG.exception("Nie udało się zapisać ustawień")

    def _startup_update_check(self) -> bool:
        if not bool(self.settings_data.get("check_updates", True)):
            return False
        last_check = int(self.settings_data.get("last_update_check", 0) or 0)
        if int(time.time()) - last_check < 6 * 60 * 60:
            return False
        self.check_for_updates(manual=False)
        return False

    def check_for_updates(self, manual: bool = False) -> None:
        if self._update_check_in_progress:
            if manual:
                info(self, "Aktualizacje", "Sprawdzanie aktualizacji już trwa.")
            return
        self._update_check_in_progress = True
        self.update_button.set_sensitive(False)

        def worker() -> None:
            release: LatestRelease | None = None
            error: Exception | None = None
            try:
                release = fetch_latest_release()
            except Exception as exc:  # odpowiedź sieciowa jest raportowana w wątku GTK
                error = exc
            GLib.idle_add(self._finish_update_check, release, error, manual)

        threading.Thread(target=worker, name="sesyjka-update-check", daemon=True).start()

    def _finish_update_check(
        self,
        release: LatestRelease | None,
        error: Exception | None,
        manual: bool,
    ) -> bool:
        self._update_check_in_progress = False
        self.update_button.set_sensitive(True)
        if error is not None:
            LOG.warning("Sprawdzanie aktualizacji nie powiodło się: %s", error)
            if manual:
                info(self, "Błąd aktualizacji", str(error), error=True)
            return False

        self.settings_data["last_update_check"] = int(time.time())
        self._save_current_settings()
        if release is None:
            return False
        try:
            newer = is_newer_version(release.version, APP_VERSION)
        except ValueError as exc:
            LOG.warning("Nieprawidłowy numer wydania: %s", exc)
            if manual:
                info(self, "Błąd aktualizacji", str(exc), error=True)
            return False
        if newer:
            self.show_update_dialog(release)
        elif manual:
            info(self, "Aktualizacje", f"Używasz najnowszej wersji {APP_VERSION}.")
        return False

    def _open_release_page(self, url: str | None = None) -> None:
        try:
            Gio.AppInfo.launch_default_for_uri(url or release_page_url(), None)
        except GLib.Error as exc:
            info(self, "Nie można otworzyć strony", str(exc), error=True)

    def show_update_dialog(self, release: LatestRelease) -> None:
        channel = detect_install_channel()
        dialog = ModalWindow(self, "Dostępna aktualizacja", width=620, height=430)
        heading = Gtk.Label(label=f"Sesyjka {release.version}")
        heading.add_css_class("title-1")
        heading.set_halign(Gtk.Align.START)
        description = Gtk.Label(
            label=(
                f"Zainstalowana wersja: {APP_VERSION}\n"
                f"Kanał instalacji: {channel}\n\n"
                + (release.body[:1800] or "Wydanie nie zawiera opisu zmian.")
            ),
            wrap=True,
            selectable=True,
            xalign=0.0,
            yalign=0.0,
        )
        description.set_vexpand(True)
        dialog.root_box.append(heading)
        dialog.add_scrolled_content(description)

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        buttons.set_halign(Gtk.Align.END)
        later = Gtk.Button(label="Później")
        later.connect("clicked", lambda _button: dialog.close())
        page = Gtk.Button(label="Strona wydania")
        page.connect("clicked", lambda _button: self._open_release_page(release.html_url))
        buttons.append(page)
        buttons.append(later)
        if channel != "local":
            update = Gtk.Button(label="Aktualizuj")
            update.add_css_class("suggested-action")
            update.connect(
                "clicked",
                lambda _button: self._install_release(release, channel, dialog),
            )
            buttons.append(update)
            dialog.set_default_widget(update)
        dialog.root_box.append(buttons)
        dialog.present()

    def _install_release(
        self,
        release: LatestRelease,
        channel: str,
        source_dialog: Gtk.Window,
    ) -> None:
        source_dialog.close()
        progress = ModalWindow(self, "Aktualizacja", width=500, height=250)
        spinner = Gtk.Spinner()
        spinner.start()
        spinner.set_halign(Gtk.Align.CENTER)
        label = Gtk.Label(
            label=(
                "Pobieranie i weryfikowanie pakietu. System może poprosić "
                "o hasło administratora przez Polkit."
            ),
            wrap=True,
            xalign=0.0,
        )
        progress.root_box.append(spinner)
        progress.root_box.append(label)
        progress.present()

        def worker() -> None:
            error: Exception | None = None
            try:
                download_and_install(release, channel)
            except Exception as exc:
                error = exc
            GLib.idle_add(self._finish_install_update, progress, release, error)

        threading.Thread(target=worker, name="sesyjka-update-install", daemon=True).start()

    def _finish_install_update(
        self,
        progress: Gtk.Window,
        release: LatestRelease,
        error: Exception | None,
    ) -> bool:
        progress.close()
        if error is not None:
            LOG.error(
                "Aktualizacja nie została zainstalowana",
                exc_info=(type(error), error, error.__traceback__),
            )
            info(self, "Aktualizacja nieudana", str(error), error=True)
            return False
        info(
            self,
            "Aktualizacja zainstalowana",
            f"Zainstalowano wersję {release.version}. Zamknij i uruchom ponownie Sesyjkę.",
        )
        return False

    def show_transfer(self) -> None:
        dialog = TransferWindow(
            self,
            self.databases,
            self.repository,
            on_database_change=self.refresh_all,
            on_guest_change=self.update_guest_state,
        )
        dialog.present()

    def show_help(self) -> None:
        dialog = ModalWindow(self, "Instrukcja obsługi", width=760, height=680)
        help_text = (
            "SYSTEMY RPG\n"
            "Dodawaj systemy gry oraz pozycje typu Podręcznik Główny, Suplement, Inne i Grupa. "
            "Pozycje można przypisywać do systemu oraz do rekordów typu Grupa. "
            "Tabela obsługuje rozwijanie hierarchii, sortowanie, wyszukiwanie i filtry kolumnowe.\n\n"
            "SESJE RPG\n"
            "Każda sesja wymaga daty, istniejącego systemu i co najmniej jednego gracza. "
            "Mistrz gry jest opcjonalny, co umożliwia sesje GM-less. Można zapisać kampanię, "
            "jednostrzał, tryb gry, tytuły oraz notatki. Graczy można szybko zaznaczać według grup.\n\n"
            "GRACZE I WYDAWCY\n"
            "Zakładki umożliwiają pełne dodawanie, edycję, usuwanie, sortowanie i filtrowanie. "
            "Usunięcie rekordu powiązanego z innymi danymi jest blokowane, aby nie tworzyć osieroconych odwołań.\n\n"
            "GRY PLANSZOWE\n"
            "Osobna baza planszowe.db przechowuje gry planszowe i karciane, zakres liczby graczy, czas rozgrywki, "
            "minimalny wiek, cenę, status gry i status kolekcji.\n\n"
            "STATYSTYKI\n"
            "Karty liczbowe przełączają wykresy ilości. Zestawienia odświeżają się po operacjach CRUD "
            "oraz po użyciu przycisku odświeżania.\n\n"
            "BAZY DANYCH\n"
            "Przycisk baz danych otwiera eksport ZIP, eksport do folderu, eksport XLSX, eksport sesji do ICS i CSV, "
            "import ZIP lub folderu oraz tryb gościa tylko do odczytu. Import tworzy kopię zapasową własnych baz.\n\n"
            "SKRÓTY\n"
            "Ctrl+N dodaje rekord w aktywnej zakładce. Ctrl+R odświeża dane. Ctrl+Q zamyka program. "
            "Dwuklik edytuje rekord, a prawy przycisk myszy otwiera menu kontekstowe.\n\n"
            "AKTUALIZACJE\n"
            "Program sprawdza najnowsze wydanie GitHub podczas uruchamiania, nie częściej niż co 6 godzin. "
            "Przycisk aktualizacji w nagłówku uruchamia kontrolę ręczną. Pakiety DEB, RPM i instalacja ogólna "
            "mogą zostać zaktualizowane po potwierdzeniu uprawnień administratora.\n\n"
            "DANE\n"
            f"Bazy użytkownika: {self.databases.own_root}"
        )
        label = Gtk.Label(label=help_text, wrap=True, selectable=True, xalign=0.0, yalign=0.0)
        label.set_max_width_chars(90)
        dialog.add_scrolled_content(label)
        close = Gtk.Button(label="Zamknij")
        close.set_halign(Gtk.Align.END)
        close.connect("clicked", lambda _button: dialog.close())
        dialog.root_box.append(close)
        dialog.present()

    def show_history(self) -> None:
        dialog = ModalWindow(self, "Historia zmian", width=720, height=620)
        history_text = (
            "0.8.6\n"
            "Dodano typ pozycji Grupa. Tylko rekordy tego typu mogą być wybierane w polu Grupa, "
            "a lista jest ograniczona do grup z wybranego systemu RPG. Usunięto typy Przygoda i Dodatek z formularza, "
            "bez zmiany nazw kolumn ani schematu bazy danych. Wycofano kolorowanie wierszy zależne od statusu. "
            "Przycisk baz danych ponownie używa ikony zapisu, a przycisk aktualizacji ikony software-update-available.\n\n"
            "0.8.5\n"
            "Usunięto nieobsługiwane stylowanie prywatnych widgetów wierszy Gtk.ColumnView, które na części wersji GTK powodowało błędy dostępności i SIGSEGV. "
            "Tabele korzystają teraz wyłącznie z publicznych mechanizmów GTK i bezpiecznego stylu zaznaczenia.\n\n"
            "0.8.4\n"
            "Uproszczono formularz systemu gry, powiązano planszówki i karcianki z bazą wydawców, "
            "usunięto notatki z ich formularza oraz dodano klikalne strony WWW wydawców.\n\n"
            "0.8.3\n"
            "Kolory statusu są przypisywane wewnętrznym widgetom całych wierszy, a pasy używają selektorów CSS GTK. "
            "Podgrupy suplementów są zapisywane separatorem |, język wybiera się z listy, a niepoprawny ISBN wyświetla ostrzeżenie bez blokowania zapisu.\n\n"
            "0.8.2\n"
            "Kolory statusu kolekcji obejmują całe wiersze, a wszystkie tabele mają naprzemienne pasy. "
            "Suplementy obsługują wielokrotny wybór podgrup, a pole waluty zakupu podpowiada popularne kody.\n\n"
            "0.8.1\n"
            "Kolory pozycji RPG zależą od statusu kolekcji. Poprawiono ikonę baz danych i przycisk potwierdzenia importu, "
            "dodano sumę wartości pozycji oraz odstęp z separatorem pomiędzy tabelami statystyk.\n\n"
            "0.8.0\n"
            "Dodano osobną bazę i zakładkę gier planszowych oraz karcianych, eksport sesji do kalendarzy ICS i CSV, "
            "kolorowanie pozycji RPG oraz dynamiczne pola cen w formularzu pozycji RPG.\n\n"
            "0.7.0\n"
            "Dodano automatyczne budowanie pakietów DEB, RPM i instalatora ogólnego przy publikowaniu wydania GitHub. "
            "Aplikacja wykrywa nowe stabilne wydania, weryfikuje sumy SHA-256 i aktualizuje właściwy kanał instalacji przez Polkit. "
            "Usunięto pliki Flatpak i Flathub.\n\n"
            "0.6.4\n"
            "Rozdzielono uruchamianie lokalne od instalacji systemowej. Dodano pełny instalator do /opt i /usr/local, "
            "systemowy deinstalator, komplet zrzutów ekranu, eksport baz do folderu, walidację importowanych baz, "
            "szybki wybór grup graczy oraz dodatkowe kontrole integralności między bazami.\n\n"
            "0.6.2-0.6.3\n"
            "Dodano separator statystyk, ikony menu kontekstowego, integrację ikony Wayland i wcześniejsze pliki pakowania.\n\n"
            "0.6.0-0.6.1\n"
            "Dodano hierarchiczne tabele, sortowanie, filtry kolumnowe, menu kontekstowe, walidację sesji, popovery Adwaita i wykresy ilości."
        )
        label = Gtk.Label(label=history_text, wrap=True, selectable=True, xalign=0.0, yalign=0.0)
        label.set_max_width_chars(88)
        dialog.add_scrolled_content(label)
        close = Gtk.Button(label="Zamknij")
        close.set_halign(Gtk.Align.END)
        close.connect("clicked", lambda _button: dialog.close())
        dialog.root_box.append(close)
        dialog.present()

    def show_about(self) -> None:
        dialog = ModalWindow(self, "O programie", width=560, height=430)
        title = Gtk.Label(label=f"{APP_NAME} {APP_VERSION}")
        title.add_css_class("title-1")
        title.set_halign(Gtk.Align.START)
        description = Gtk.Label(
            label=(
                "Natywna aplikacja GTK4 i Libadwaita dla Linuksa do zarządzania kolekcją systemów RPG, "
                "sesjami, graczami, wydawcami oraz grami planszowymi i karcianymi. "
                "Cztery bazy projektu źródłowego pozostają zgodne, a planszowe.db jest niezależnym rozszerzeniem."
            ),
            wrap=True,
            xalign=0.0,
        )
        details = Gtk.Label(
            label=(
                f"Identyfikator: {APP_ID}\n"
                f"Repozytorium: {UPDATE_REPOSITORY}\n"
                f"Kanał instalacji: {detect_install_channel()}\n"
                f"Katalog danych: {self.databases.own_root}"
            ),
            selectable=True,
            xalign=0.0,
        )
        update_check = Gtk.CheckButton(label="Automatycznie sprawdzaj aktualizacje")
        update_check.set_active(bool(self.settings_data.get("check_updates", True)))

        def update_preference(button: Gtk.CheckButton) -> None:
            self.settings_data["check_updates"] = button.get_active()
            self._save_current_settings()

        update_check.connect("toggled", update_preference)
        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        buttons.set_halign(Gtk.Align.END)
        check = Gtk.Button(label="Sprawdź aktualizacje")
        check.connect("clicked", lambda _button: self.check_for_updates(manual=True))
        history = Gtk.Button(label="Historia zmian")
        history.connect("clicked", lambda _button: self.show_history())
        close = Gtk.Button(label="Zamknij")
        close.connect("clicked", lambda _button: dialog.close())
        buttons.append(check)
        buttons.append(history)
        buttons.append(close)
        dialog.root_box.append(title)
        dialog.root_box.append(description)
        dialog.root_box.append(details)
        dialog.root_box.append(update_check)
        dialog.root_box.append(buttons)
        dialog.present()

    def on_close_request(self, _window: Gtk.Window) -> bool:
        self._save_current_settings()
        return False


class SesyjkaApplication(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.window: SesyjkaWindow | None = None
        self.databases = DatabaseManager()

    def do_startup(self) -> None:
        # Wirtualne metody klas GObject nie są zwykłymi metodami Pythona.
        # Łańcuch wywołań należy wykonać jawnie przez bezpośrednią klasę bazową.
        Adw.Application.do_startup(self)
        self._register_application_icon()
        self._add_action("quit", lambda *_args: self.quit(), ["<Primary>q"])
        self._add_action("refresh", lambda *_args: self.window.refresh_all() if self.window else None, ["<Primary>r"])
        self._add_action("new", lambda *_args: self._new_record(), ["<Primary>n"])

    @staticmethod
    def _register_application_icon() -> None:
        """Register the themed application icon for GTK and window-manager fallbacks."""
        display = Gdk.Display.get_default()
        if display is None:
            Gtk.Window.set_default_icon_name(APP_ID)
            return

        icon_theme = Gtk.IconTheme.get_for_display(display)
        source_root = Path(__file__).resolve().parents[1] / "data" / "icons"
        packaged_root = Path(__file__).resolve().parent / "resources" / "icons"
        for icon_root in (source_root, packaged_root):
            if icon_root.is_dir():
                icon_theme.add_search_path(str(icon_root))
        Gtk.Window.set_default_icon_name(APP_ID)

    def _add_action(self, name: str, callback: object, accelerators: list[str]) -> None:
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)
        self.set_accels_for_action(f"app.{name}", accelerators)

    def _new_record(self) -> None:
        if not self.window or self.databases.guest_mode:
            return
        child = self.window.stack.get_visible_child()
        if child is not None and hasattr(child, "open_editor"):
            child.open_editor(None)

    def do_activate(self) -> None:
        if self.window is None:
            migrated = migrate_legacy_databases()
            try:
                self.databases.initialize()
            except Exception as exc:
                temporary = Adw.ApplicationWindow(application=self, title=APP_NAME)
                temporary.set_default_size(500, 220)
                temporary.present()
                info(temporary, "Błąd inicjalizacji", str(exc), error=True)
                return
            self.window = SesyjkaWindow(self, self.databases)
            if migrated:
                GLib.idle_add(
                    lambda: info(
                        self.window,
                        "Migracja danych",
                        f"Skopiowano {len(migrated)} starsze bazy do katalogu XDG: {self.databases.own_root}",
                    )
                    or False
                )
        self.window.present()
