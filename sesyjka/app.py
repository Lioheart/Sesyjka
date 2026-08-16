from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from . import APP_ID, APP_NAME, APP_VERSION, UPDATE_REPOSITORY
from .cloud import CloudAuthError, CloudError, CloudOfflineError, CloudService, Conflict, DEFAULT_SYNC_INTERVAL
from .config import (
    DEFAULT_SUPABASE_PUBLISHABLE_KEY,
    DEFAULT_SUPABASE_URL,
    load_settings,
    migrate_legacy_databases,
    save_settings,
)
from .database_manager import DatabaseManager
from .dialogs import ModalWindow, info
from .pages import BoardGamesPage, DigitalResourcesPage, PlayersPage, PublishersPage, SessionsPage, StatisticsPage, SystemsPage
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
.app-main-title {
  font-size: 22px;
  font-weight: 800;
}
.app-main-subtitle {
  font-size: 12px;
  opacity: 0.72;
}
.cloud-status-label {
  font-size: 12px;
}
.cloud-status-error {
  color: @error_color;
}
.cloud-status-warning {
  color: @warning_color;
}
.cloud-status-ok {
  color: @success_color;
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
        self.cloud = CloudService(databases)
        self._font_provider = None
        self.style_manager = Adw.StyleManager.get_default()
        self._update_check_in_progress = False
        self._cloud_sync_in_progress = False
        self._cloud_last_error = ""
        self._cloud_last_error_kind = ""
        self._cloud_last_attempt = 0
        self.connect("close-request", self.on_close_request)
        self.set_icon_name(APP_ID)

        self.header = Adw.HeaderBar()
        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        title_box.set_halign(Gtk.Align.CENTER)
        title = Gtk.Label(label=APP_NAME)
        title.add_css_class("app-main-title")
        subtitle = Gtk.Label(label="Kolekcja RPG, sesje, gry planszowe i zasoby cyfrowe")
        subtitle.add_css_class("app-main-subtitle")
        title_box.append(title)
        title_box.append(subtitle)
        self.header.set_title_widget(title_box)

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

        self.cloud_button = Gtk.Button()
        cloud_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        cloud_icon_name = "network-server-symbolic"
        cloud_display = Gdk.Display.get_default()
        if cloud_display is not None:
            cloud_theme = Gtk.IconTheme.get_for_display(cloud_display)
            if not cloud_theme.has_icon(cloud_icon_name):
                cloud_icon_name = "view-refresh-symbolic"
        self.cloud_icon = Gtk.Image.new_from_icon_name(cloud_icon_name)
        self.cloud_status_label = Gtk.Label(label="Cloud: wyłączona")
        self.cloud_status_label.add_css_class("cloud-status-label")
        cloud_box.append(self.cloud_icon)
        cloud_box.append(self.cloud_status_label)
        self.cloud_button.set_child(cloud_box)
        self.cloud_button.set_tooltip_text("Sesyjka Cloud: konto i synchronizacja")
        self.cloud_button.connect("clicked", lambda _button: self.show_cloud())
        self.header.pack_end(self.cloud_button)

        update_icon_name = "software-update-available-symbolic"
        display = Gdk.Display.get_default()
        if display is not None:
            icon_theme = Gtk.IconTheme.get_for_display(display)
            if not icon_theme.has_icon(update_icon_name):
                update_icon_name = "view-refresh-symbolic"
        self.update_button = Gtk.Button.new_from_icon_name(update_icon_name)
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
            "digital_resources": DigitalResourcesPage(self, self.repository),
            "statistics": StatisticsPage(self, self.repository),
        }
        self.stack.add_titled(self.pages["systems"], "systems", "Systemy RPG")
        self.stack.add_titled(self.pages["sessions"], "sessions", "Sesje RPG")
        self.stack.add_titled(self.pages["players"], "players", "Gracze")
        self.stack.add_titled(self.pages["publishers"], "publishers", "Wydawcy")
        self.stack.add_titled(self.pages["board_games"], "board_games", "Gry planszowe")
        self.stack.add_titled(self.pages["digital_resources"], "digital_resources", "Zasoby cyfrowe")
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
        self._update_cloud_status()
        GLib.timeout_add_seconds(3, self._startup_cloud_sync)
        GLib.timeout_add_seconds(30, self._cloud_periodic_tick)
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
        for key in ("systems", "sessions", "players", "publishers", "board_games", "digital_resources"):
            page = self.pages[key]
            if page is not visible:
                page.refresh()
        if hasattr(self, "cloud_status_label"):
            self._update_cloud_status()

    def update_guest_state(self) -> None:
        guest = self.databases.guest_mode
        self.guest_banner.set_visible(guest)
        if guest:
            self.guest_banner.set_text(f"TRYB GOŚCIA. Dane tylko do odczytu: {self.databases.active_root}")
        for page in self.pages.values():
            page.set_read_only(guest)
        self.refresh_all()
        if hasattr(self, "cloud_status_label"):
            self._update_cloud_status()

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

    def _cloud_config_values(self) -> tuple[str, str]:
        # Produkcyjny backend Sesyjka Cloud jest częścią konfiguracji aplikacji.
        # Zmienne środowiskowe pozostają wyłącznie jako override dla developmentu
        # i testów, dzięki czemu zwykły użytkownik nie konfiguruje Supabase.
        url = os.environ.get("SESYJKA_SUPABASE_URL", DEFAULT_SUPABASE_URL)
        key = os.environ.get("SESYJKA_SUPABASE_KEY", DEFAULT_SUPABASE_PUBLISHABLE_KEY)
        return url.strip(), key.strip()

    def _cloud_configured(self) -> bool:
        url, key = self._cloud_config_values()
        return bool(url and key)

    def _cloud_auto_enabled(self) -> bool:
        return bool(self.settings_data.get("cloud_auto_sync", True))

    def _cloud_interval(self) -> int:
        try:
            value = int(self.settings_data.get("cloud_sync_interval", DEFAULT_SYNC_INTERVAL))
        except (TypeError, ValueError):
            value = DEFAULT_SYNC_INTERVAL
        return min(86400, max(60, value))

    def _set_cloud_status(self, text: str, state: str = "neutral") -> None:
        self.cloud_status_label.set_text(text)
        for css_class in ("cloud-status-error", "cloud-status-warning", "cloud-status-ok"):
            self.cloud_status_label.remove_css_class(css_class)
        if state == "error":
            self.cloud_status_label.add_css_class("cloud-status-error")
        elif state == "warning":
            self.cloud_status_label.add_css_class("cloud-status-warning")
        elif state == "ok":
            self.cloud_status_label.add_css_class("cloud-status-ok")

    def _update_cloud_status(self) -> None:
        if self.databases.guest_mode:
            self._set_cloud_status("Cloud: gość", "warning")
            self.cloud_button.set_tooltip_text("Synchronizacja jest wyłączona w trybie gościa")
            return
        if not self._cloud_configured():
            self._set_cloud_status("Cloud: skonfiguruj")
            self.cloud_button.set_tooltip_text("Skonfiguruj projekt Supabase i konto Sesyjka Cloud")
            return
        if not self.cloud.signed_in:
            self._set_cloud_status("Cloud: zaloguj")
            self.cloud_button.set_tooltip_text("Zaloguj się do Sesyjka Cloud")
            return
        conflicts = len(self.cloud.conflicts)
        if conflicts:
            self._set_cloud_status(f"Cloud: konflikty {conflicts}", "warning")
            self.cloud_button.set_tooltip_text("Sesyjka Cloud wymaga rozwiązania konfliktów")
            return
        if self._cloud_sync_in_progress:
            self._set_cloud_status("Cloud: synchronizacja…")
            self.cloud_button.set_tooltip_text("Trwa synchronizacja z Supabase")
            return
        if self._cloud_last_error:
            if self._cloud_last_error_kind == "offline":
                self._set_cloud_status("Cloud: offline", "warning")
            else:
                self._set_cloud_status("Cloud: błąd", "error")
            self.cloud_button.set_tooltip_text(self._cloud_last_error)
            return
        pending = self.cloud.pending_local_databases
        if pending:
            self._set_cloud_status("Cloud: oczekuje", "ok")
            minutes = max(1, self._cloud_interval() // 60)
            self.cloud_button.set_tooltip_text(
                f"Zmiany zapisano lokalnie. Synchronizacja okresowa co {minutes} min lub ręcznie."
            )
            return
        last_sync = int(self.cloud.store.get_meta("last_sync_at") or 0)
        if last_sync:
            timestamp = time.strftime("%H:%M", time.localtime(last_sync))
            self._set_cloud_status(f"Cloud: ✓ {timestamp}", "ok")
            email = self.cloud.session.email if self.cloud.session else ""
            self.cloud_button.set_tooltip_text(f"Zsynchronizowano o {timestamp}" + (f" · {email}" if email else ""))
        else:
            self._set_cloud_status("Cloud: gotowa", "ok")
            self.cloud_button.set_tooltip_text("Konto połączone. Dane oczekują na pierwszą synchronizację.")

    def _cloud_sync_due(self) -> bool:
        last_sync = int(self.cloud.store.get_meta("last_sync_at") or 0)
        reference = max(last_sync, self._cloud_last_attempt)
        if reference <= 0:
            return True
        return int(time.time()) - reference >= self._cloud_interval()

    def _startup_cloud_sync(self) -> bool:
        if (
            self._cloud_configured()
            and self.cloud.signed_in
            and self._cloud_auto_enabled()
            and not self.databases.guest_mode
            and self._cloud_sync_due()
        ):
            self.trigger_cloud_sync(manual=False)
        else:
            self._update_cloud_status()
        return False

    def _cloud_periodic_tick(self) -> bool:
        self._update_cloud_status()
        if (
            self._cloud_configured()
            and self.cloud.signed_in
            and self._cloud_auto_enabled()
            and not self.databases.guest_mode
            and not self._cloud_sync_in_progress
            and self._cloud_sync_due()
        ):
            self.trigger_cloud_sync(manual=False)
        return True

    def trigger_cloud_sync(self, manual: bool = False) -> None:
        if self.databases.guest_mode:
            if manual:
                info(self, "Sesyjka Cloud", "Synchronizacja jest wyłączona w trybie gościa.")
            return
        if not self._cloud_configured():
            if manual:
                self.show_cloud()
            return
        if not self.cloud.signed_in:
            if manual:
                self.show_cloud()
            return
        if self._cloud_sync_in_progress:
            if manual:
                info(self, "Sesyjka Cloud", "Synchronizacja już trwa.")
            return
        self._cloud_sync_in_progress = True
        self._cloud_last_attempt = int(time.time())
        self._cloud_last_error = ""
        self._cloud_last_error_kind = ""
        self._update_cloud_status()
        url, key = self._cloud_config_values()

        def worker() -> None:
            report = None
            error: Exception | None = None
            try:
                report = self.cloud.sync(url, key)
            except Exception as exc:
                error = exc
            GLib.idle_add(self._finish_cloud_sync, report, error, manual)

        threading.Thread(target=worker, name="sesyjka-cloud-sync", daemon=True).start()

    def _finish_cloud_sync(self, report: object, error: Exception | None, manual: bool) -> bool:
        self._cloud_sync_in_progress = False
        if error is not None:
            LOG.warning("Synchronizacja Sesyjka Cloud nie powiodła się: %s", error)
            self._cloud_last_error = str(error)
            self._cloud_last_error_kind = "offline" if isinstance(error, CloudOfflineError) else "error"
            self._update_cloud_status()
            if manual:
                info(self, "Błąd synchronizacji", str(error), error=True)
            return False
        self._cloud_last_error = ""
        self._cloud_last_error_kind = ""
        self.refresh_all()
        self._update_cloud_status()
        if manual and report is not None:
            uploaded = int(getattr(report, "uploaded", 0))
            downloaded = int(getattr(report, "downloaded", 0))
            deleted_local = int(getattr(report, "deleted_local", 0))
            deleted_remote = int(getattr(report, "deleted_remote", 0))
            conflicts = int(getattr(report, "conflicts", 0))
            message = (
                f"Wysłano: {uploaded}\n"
                f"Pobrano: {downloaded}\n"
                f"Usunięto lokalnie: {deleted_local}\n"
                f"Usunięto w chmurze: {deleted_remote}\n"
                f"Konflikty: {conflicts}"
            )
            info(self, "Synchronizacja zakończona", message)
        return False

    def show_cloud(self) -> None:
        dialog = ModalWindow(self, "Sesyjka Cloud", width=760, height=680)
        heading = Gtk.Label(label="Sesyjka Cloud")
        heading.add_css_class("title-1")
        heading.set_halign(Gtk.Align.START)
        description = Gtk.Label(
            label=(
                "Sesyjka Cloud używa konta Discord do logowania przez Supabase Auth. "
                "Program zapisuje dane najpierw w lokalnych bazach SQLite. sync.db przechowuje "
                "wyłącznie stan synchronizacji, kolejkę zmian i konflikty. Automatyczna "
                "synchronizacja działa okresowo, nie po każdej edycji."
            ),
            wrap=True,
            xalign=0.0,
        )
        dialog.root_box.append(heading)
        dialog.root_box.append(description)

        account_frame = Gtk.Frame(label="Konto użytkownika")
        account_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        account_box.set_margin_top(12)
        account_box.set_margin_bottom(12)
        account_box.set_margin_start(12)
        account_box.set_margin_end(12)
        dialog.root_box.append(account_frame)
        account_frame.set_child(account_box)

        status = Gtk.Label(wrap=True, xalign=0.0)
        account_box.append(status)

        if not self.cloud.signed_in:
            login_info = Gtk.Label(
                label=(
                    "Kliknij poniżej, aby zalogować się przez Discord w domyślnej przeglądarce. "
                    "Pierwsze logowanie automatycznie tworzy konto w Supabase Auth. "
                    "Po autoryzacji synchronizacja rozpocznie się automatycznie."
                ),
                wrap=True,
                xalign=0.0,
            )
            account_box.append(login_info)
            signin = Gtk.Button(label="Zaloguj przez Discord")
            signin.add_css_class("suggested-action")
            signin.set_halign(Gtk.Align.END)
            account_box.append(signin)

            def auth_discord(_button: Gtk.Button) -> None:
                signin.set_sensitive(False)
                status.remove_css_class("error")
                status.set_text("Otwieranie Discord w przeglądarce. Po zalogowaniu wróć do Sesyjki…")
                url, key = self._cloud_config_values()

                def worker() -> None:
                    result: object = None
                    error: Exception | None = None
                    try:
                        result = self.cloud.sign_in_with_discord(url, key)
                    except Exception as exc:
                        error = exc
                    GLib.idle_add(finish_discord_auth, result, error)

                threading.Thread(target=worker, name="sesyjka-cloud-discord-auth", daemon=True).start()

            def finish_discord_auth(result: object, error: Exception | None) -> bool:
                signin.set_sensitive(True)
                if error is not None:
                    status.set_text(str(error))
                    status.add_css_class("error")
                    self._cloud_last_error = str(error)
                    self._cloud_last_error_kind = "offline" if isinstance(error, CloudOfflineError) else "error"
                    self._update_cloud_status()
                    return False
                status.remove_css_class("error")
                session = result if hasattr(result, "user_id") else self.cloud.session
                identity = getattr(session, "email", "") or getattr(session, "user_id", "")
                status.set_text(f"Zalogowano przez Discord: {identity}")
                self._cloud_last_error = ""
                self._cloud_last_error_kind = ""
                self._update_cloud_status()
                dialog.close()
                self.trigger_cloud_sync(manual=False)
                return False

            signin.connect("clicked", auth_discord)
        else:
            session = self.cloud.session
            provider_name = "Discord" if session.provider == "discord" else (session.provider.capitalize() if session.provider else "Sesyjka Cloud")
            account_box.append(
                Gtk.Label(
                    label=f"Zalogowano przez {provider_name}: {session.email or session.user_id}",
                    xalign=0.0,
                )
            )
            account_box.append(Gtk.Label(label=f"Urządzenie: {self.cloud.store.device_id}", xalign=0.0, selectable=True))
            last_sync = int(self.cloud.store.get_meta("last_sync_at") or 0)
            last_text = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(last_sync)) if last_sync else "jeszcze nie wykonano"
            account_box.append(Gtk.Label(label=f"Ostatnia synchronizacja: {last_text}", xalign=0.0))

            auto_sync = Gtk.CheckButton(label="Automatycznie synchronizuj okresowo")
            auto_sync.set_active(self._cloud_auto_enabled())
            account_box.append(auto_sync)
            interval_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            interval_box.append(Gtk.Label(label="Interwał synchronizacji:"))
            interval = Gtk.SpinButton.new_with_range(1, 1440, 1)
            interval.set_value(self._cloud_interval() / 60)
            interval_box.append(interval)
            interval_box.append(Gtk.Label(label="min"))
            account_box.append(interval_box)
            sync_policy = Gtk.Label(
                label=(
                    "Zmiany są zapisywane lokalnie natychmiast i oczekują do kolejnego interwału. "
                    "Synchronizacja przesyła tylko zmienione rekordy. Jeśli ten sam rekord zmieniono "
                    "lokalnie i w chmurze, pierwszeństwo ma lokalna baza danych."
                ),
                wrap=True,
                xalign=0.0,
            )
            sync_policy.add_css_class("dim-label")
            account_box.append(sync_policy)

            def update_sync_preferences(*_args: object) -> None:
                self.settings_data["cloud_auto_sync"] = auto_sync.get_active()
                self.settings_data["cloud_sync_interval"] = int(interval.get_value()) * 60
                self._save_current_settings()

            auto_sync.connect("toggled", update_sync_preferences)
            interval.connect("value-changed", update_sync_preferences)

            conflict_count = len(self.cloud.conflicts)
            action_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            action_box.set_halign(Gtk.Align.END)
            conflicts = Gtk.Button(label=f"Konflikty ({conflict_count})")
            conflicts.set_sensitive(conflict_count > 0)
            sync = Gtk.Button(label="Synchronizuj teraz")
            sync.add_css_class("suggested-action")
            logout = Gtk.Button(label="Wyloguj")
            action_box.append(conflicts)
            action_box.append(logout)
            action_box.append(sync)
            account_box.append(action_box)
            sync.connect("clicked", lambda _button: (dialog.close(), self.trigger_cloud_sync(manual=True)))
            conflicts.connect("clicked", lambda _button: (dialog.close(), self.show_cloud_conflicts()))

            def logout_clicked(_button: Gtk.Button) -> None:
                url, key = self._cloud_config_values()
                logout.set_sensitive(False)
                status.set_text("Wylogowywanie…")

                def worker() -> None:
                    error: Exception | None = None
                    try:
                        self.cloud.sign_out(url, key)
                    except Exception as exc:
                        error = exc
                    GLib.idle_add(finish_logout, error)

                threading.Thread(target=worker, name="sesyjka-cloud-logout", daemon=True).start()

            def finish_logout(error: Exception | None) -> bool:
                if error:
                    LOG.warning("Wylogowanie chmurowe: %s", error)
                self._cloud_last_error = ""
                self._cloud_last_error_kind = ""
                self._update_cloud_status()
                dialog.close()
                return False

            logout.connect("clicked", logout_clicked)

        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        footer.set_halign(Gtk.Align.END)
        close = Gtk.Button(label="Zamknij")
        close.connect("clicked", lambda _button: dialog.close())
        footer.append(close)
        dialog.root_box.append(footer)
        dialog.present()

    def show_cloud_conflicts(self) -> None:
        conflicts = self.cloud.conflicts
        if not conflicts:
            info(self, "Konflikty synchronizacji", "Nie ma nierozwiązanych konfliktów.")
            return
        dialog = ModalWindow(self, "Konflikty synchronizacji", width=1040, height=760)
        intro = Gtk.Label(
            label=(
                "Ten sam rekord został zmieniony lokalnie i w chmurze od ostatniej synchronizacji. "
                "Wybierz wersję, która ma zostać zachowana. Decyzja jest wykonywana osobno dla każdego rekordu."
            ),
            wrap=True,
            xalign=0.0,
        )
        dialog.root_box.append(intro)
        list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for conflict in conflicts:
            expander = Gtk.Expander(label=self._conflict_title(conflict))
            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            compare = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            local_panel = self._conflict_payload_panel("Lokalne", conflict.local_payload, conflict.local_deleted)
            remote_panel = self._conflict_payload_panel("Chmura", conflict.remote_payload, conflict.remote_deleted)
            compare.append(local_panel)
            compare.append(remote_panel)
            content.append(compare)
            actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            actions.set_halign(Gtk.Align.END)
            keep_local = Gtk.Button(label="Zachowaj lokalne")
            keep_cloud = Gtk.Button(label="Zachowaj chmurę")
            keep_cloud.add_css_class("suggested-action")
            keep_local.connect("clicked", lambda _button, cid=conflict.id: self._resolve_cloud_conflict(cid, "local", dialog))
            keep_cloud.connect("clicked", lambda _button, cid=conflict.id: self._resolve_cloud_conflict(cid, "remote", dialog))
            actions.append(keep_local)
            actions.append(keep_cloud)
            content.append(actions)
            expander.set_child(content)
            list_box.append(expander)
        dialog.add_scrolled_content(list_box)
        close = Gtk.Button(label="Zamknij")
        close.set_halign(Gtk.Align.END)
        close.connect("clicked", lambda _button: dialog.close())
        dialog.root_box.append(close)
        dialog.present()

    def _conflict_title(self, conflict: Conflict) -> str:
        names = {
            "publishers": "Wydawca",
            "players": "Gracz",
            "game_systems": "System RPG",
            "rpg_items": "Pozycja RPG",
            "sessions": "Sesja",
            "session_players": "Uczestnik sesji",
            "session_notes": "Notatka sesji",
            "board_games": "Gra planszowa/karciana",
        }
        label = names.get(conflict.entity_type, conflict.entity_type)
        local_name = (conflict.local_payload or {}).get("nazwa") or (conflict.local_payload or {}).get("nick")
        remote_name = (conflict.remote_payload or {}).get("nazwa") or (conflict.remote_payload or {}).get("nick")
        detail = local_name or remote_name or conflict.record_key
        return f"{label}: {detail}"

    def _conflict_payload_panel(self, title: str, payload: dict[str, object] | None, deleted: bool) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_hexpand(True)
        label = Gtk.Label(label=title, xalign=0.0)
        label.add_css_class("heading")
        box.append(label)
        text = "(rekord usunięty)" if deleted else json.dumps(payload or {}, ensure_ascii=False, indent=2, sort_keys=True)
        view = Gtk.TextView()
        view.set_editable(False)
        view.set_monospace(True)
        view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        view.get_buffer().set_text(text)
        scroller = Gtk.ScrolledWindow()
        scroller.set_min_content_height(240)
        scroller.set_hexpand(True)
        scroller.set_child(view)
        box.append(scroller)
        return box

    def _resolve_cloud_conflict(self, conflict_id: int, resolution: str, dialog: Gtk.Window) -> None:
        url, key = self._cloud_config_values()
        dialog.set_sensitive(False)

        def worker() -> None:
            error: Exception | None = None
            try:
                self.cloud.resolve_conflict(url, key, conflict_id, resolution)
            except Exception as exc:
                error = exc
            GLib.idle_add(finish, error)

        def finish(error: Exception | None) -> bool:
            dialog.set_sensitive(True)
            if error:
                info(self, "Błąd konfliktu", str(error), error=True)
                return False
            dialog.close()
            self.refresh_all()
            self._update_cloud_status()
            if self.cloud.conflicts:
                self.show_cloud_conflicts()
            else:
                self.trigger_cloud_sync(manual=False)
            return False

        threading.Thread(target=worker, name="sesyjka-cloud-conflict", daemon=True).start()

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
            "W formularzu pozycji numer ISBN może pobrać okładkę, tytuł, rok wydania i dostępną informację o cenie online. "
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
            "SESYJKA CLOUD\n"
            "Przycisk Cloud w nagłówku otwiera logowanie przez Discord, ręczną synchronizację i konflikty. Backend Sesyjka Cloud jest skonfigurowany w aplikacji. "
            "Dane są zapisywane najpierw lokalnie, więc brak Internetu nie blokuje pracy. Automatyczna synchronizacja "
            "uruchamia się wyłącznie okresowo lub ręcznie. sync.db zapamiętuje, które lokalne bazy zostały zmienione, "
            "a z Supabase pobierane są tylko rekordy zmienione od poprzedniej synchronizacji. Przy jednoczesnej zmianie "
            "tego samego rekordu pierwszeństwo ma lokalna baza danych.\n\n"
            "AKTUALIZACJE\n"
            "Program sprawdza najnowsze wydanie GitHub podczas uruchamiania, nie częściej niż co 6 godzin. "
            "Przycisk aktualizacji w nagłówku uruchamia kontrolę ręczną. Pakiety DEB, RPM i instalacja ogólna "
            "mogą zostać zaktualizowane po potwierdzeniu uprawnień administratora.\n\n"
            "DANE\n"
            f"Bazy użytkownika: {self.databases.own_root}\n"
            f"Stan synchronizacji: {self.databases.own_root / 'sync.db'}"
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
            "0.9.11\n"
            "Zmieniono Sesyjka Cloud na synchronizację okresową. Edycje nie wywołują już synchronizacji po kilku sekundach. sync.db śledzi lokalnie zmienione bazy, a kolejne przebiegi skanują tylko te bazy i pobierają z Supabase wyłącznie rekordy zmienione od poprzedniego kursora. Przy kolizji zmian lokalna baza ma pierwszeństwo. Dodano wykrywanie zmian wykonanych w plikach SQLite poza uruchomioną aplikacją.\n\n"
            "0.9.10\n"
            "Naprawiono bezpieczeństwo Sesyjka Cloud. Błąd synchronizacji nie pozostawia już częściowo zmienionych lokalnych baz, ponieważ zmiany z chmury są chronione kopią i automatycznym rollbackiem. Brak wiersza w Supabase nie jest traktowany jako usunięcie bez tombstone. Dodano też odzyskiwanie pustej bazy wydawców z zgodnej kopii zapasowej, gdy kolekcja nadal zawiera odwołania do wydawców.\n\n"
            "0.9.9\n"
            "DriveThruRPG ponownie zachowuje nazwę produktu jako nazwę zasobu. Dodano osobną kolumnę Nazwa pliku z przyjaznym tytułem konkretnego pliku, z fallbackiem do technicznej nazwy. Ponowna synchronizacja aktualizuje rekordy z 0.9.8 i automatycznie rozszerza zasoby.db o nowe pole.\n\n"
            "0.9.8\n"
            "Poprawiono nazwy zasobów importowanych z DriveThruRPG. Gdy jeden produkt zawiera wiele plików, każdy zasób otrzymuje nazwę konkretnego pliku zamiast powielonej nazwy produktu. Nazwa produktu jest zachowywana osobno do dopasowania zasobu do pozycji RPG. Ponowna synchronizacja aktualizuje wcześniej zaimportowane rekordy bez zmiany schematu bazy.\n\n"
            "0.9.7\n"
            "Naprawiono uwierzytelnianie DriveThruRPG. Sesyjka używa teraz surowego JWT w nagłówku Authorization zgodnie z bieżącym SDK, zachowuje pojedynczy fallback Bearer, wysyła pusty obiekt JSON do auth_key i rozróżnia błędy Application Key od błędów tokenu sesji.\n\n"
            "0.9.6\n"
            "Naprawiono synchronizację DriveThruRPG: odpowiedzi gzip/deflate są poprawnie rozpakowywane, token JWT jest wysyłany jako Bearer, a parser order_products obsługuje paginowany format JSON:API wraz z dołączonym wydawcą.\n\n"
            "0.9.4\n"
            "Dodano osobną bibliotekę zasobów cyfrowych w zasoby.db, logiczne magazyny lokalne/NAS/USB, skanowanie PDF z SHA-256, wiele lokalizacji jednego zasobu i eksperymentalny import biblioteki DriveThruRPG.\n\n"
            "0.9.3\n"
            "Backend Sesyjka Cloud jest skonfigurowany bezpośrednio w aplikacji, a GUI nie wymaga Project URL ani klucza Supabase. Dodano szybkie dodawanie zaznaczonej sesji do Google Calendar w przeglądarce oraz eksport pojedynczej sesji do ICS z otwarciem iCloud Calendar dla użytkowników Apple.\n\n"
            "0.9.1\n"
            "Logowanie Sesyjka Cloud odbywa się przez konto Discord w bezpiecznym przepływie OAuth PKCE. Po poprawnej autoryzacji synchronizacja uruchamia się automatycznie. Dodano lokalny callback tylko na 127.0.0.1 oraz czytelniejszy komunikat dla niewdrożonego backendu Supabase.\n\n"
            "0.9.0\n"
            "Dodano Sesyjka Cloud: konta Supabase Auth, osobną bazę sync.db, synchronizację lokalnych baz SQLite z chmurą bez zmian ich schematów, pracę offline, automatyczne i ręczne synchronizowanie, widoczny status w nagłówku oraz ręczne rozwiązywanie konfliktów. Powiększono również tytuł aplikacji.\n\n"
            "0.8.9\n"
            "Dodano trwały cache metadanych ISBN i informacji o braku okładki, dzięki czemu ponowne otwarcie formularza nie wykonuje kolejnych zapytań sieciowych. "
            "Przycisk Pobierz z ISBN wymusza ręczne odświeżenie danych. Dodano wewnętrzny padding formularza, krótki opis aplikacji w nagłówku oraz bezpieczny fallback ikony aktualizacji.\n\n"
            "0.8.8\n"
            "Dodano dzielony formularz pozycji RPG z panelem ISBN po prawej stronie. Open Library dostarcza metadane i okładki, "
            "a Google Books uzupełnia dane i może podać informacyjną cenę online. Puste pola nazwy i roku są uzupełniane automatycznie, "
            "istniejące wartości nie są nadpisywane bez użycia przycisku. Okładki są buforowane w katalogu XDG cache, a sieć działa w tle.\n\n"
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
                "sesjami, graczami, wydawcami, grami planszowymi oraz zasobami cyfrowymi PDF/VTT. "
                "Cztery bazy projektu źródłowego pozostają zgodne, planszowe.db i zasoby.db są niezależnymi rozszerzeniami, "
                "a sync.db przechowuje wyłącznie stan opcjonalnej synchronizacji Sesyjka Cloud."
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
                recovered_publishers = self.databases.recover_empty_publishers_from_backup()
            except Exception as exc:
                temporary = Adw.ApplicationWindow(application=self, title=APP_NAME)
                temporary.set_default_size(500, 220)
                temporary.present()
                info(temporary, "Błąd inicjalizacji", str(exc), error=True)
                return
            self.window = SesyjkaWindow(self, self.databases)
            if recovered_publishers is not None:
                GLib.idle_add(
                    lambda: info(
                        self.window,
                        "Odzyskano bazę wydawców",
                        "Wykryto pustą bazę wydawców przy istniejących odwołaniach z kolekcji. "
                        f"Przywrócono wydawcy.db z kopii: {recovered_publishers}",
                    )
                    or False
                )
            elif migrated:
                GLib.idle_add(
                    lambda: info(
                        self.window,
                        "Migracja danych",
                        f"Skopiowano {len(migrated)} starsze bazy do katalogu XDG: {self.databases.own_root}",
                    )
                    or False
                )
        self.window.present()
