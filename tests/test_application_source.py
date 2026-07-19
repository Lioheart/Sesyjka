from __future__ import annotations

import ast
import unittest
from pathlib import Path


class ApplicationSourceTests(unittest.TestCase):
    @property
    def root(self) -> Path:
        return Path(__file__).parents[1]

    def test_gobject_startup_chains_to_adw_application_explicitly(self) -> None:
        source = (self.root / "sesyjka" / "app.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        startup = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "do_startup"
        )
        calls = [node for node in ast.walk(startup) if isinstance(node, ast.Call)]
        explicit_chain = any(
            isinstance(call.func, ast.Attribute)
            and call.func.attr == "do_startup"
            and isinstance(call.func.value, ast.Attribute)
            and call.func.value.attr == "Application"
            and isinstance(call.func.value.value, ast.Name)
            and call.func.value.value.id == "Adw"
            and len(call.args) == 1
            and isinstance(call.args[0], ast.Name)
            and call.args[0].id == "self"
            for call in calls
        )
        self.assertTrue(explicit_chain)
        invalid_super_chain = any(
            isinstance(call.func, ast.Attribute)
            and call.func.attr == "do_startup"
            and isinstance(call.func.value, ast.Call)
            and isinstance(call.func.value.func, ast.Name)
            and call.func.value.func.id == "super"
            for call in calls
        )
        self.assertFalse(invalid_super_chain)

    def test_theme_switch_forces_light_and_dark_adwaita_schemes(self) -> None:
        source = (self.root / "sesyjka" / "app.py").read_text(encoding="utf-8")
        self.assertIn("Adw.ColorScheme.FORCE_DARK", source)
        self.assertIn("Adw.ColorScheme.FORCE_LIGHT", source)
        self.assertNotIn("Adw.ColorScheme.DEFAULT if", source)

    def test_table_source_contains_sort_filters_and_context_actions(self) -> None:
        source = (self.root / "sesyjka" / "widgets.py").read_text(encoding="utf-8")
        for token in (
            "Gtk.SortListModel",
            "Gtk.CustomSorter",
            "Filtry kolumnowe",
            "Gtk.GestureClick",
            "set_pointing_to",
        ):
            self.assertIn(token, source)

    def test_popovers_are_not_overridden_by_generic_background_css(self) -> None:
        source = (self.root / "sesyjka" / "app.py").read_text(encoding="utf-8")
        self.assertIn(".app-background", source)
        self.assertNotIn("\n.background,", source)
        self.assertNotIn('add_css_class("background")', source)

    def test_statistics_use_native_quantity_chart_instead_of_detail_table(self) -> None:
        page_source = (self.root / "sesyjka" / "pages" / "statistics.py").read_text(
            encoding="utf-8"
        )
        widget_source = (self.root / "sesyjka" / "widgets.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("QuantityBarChart", page_source)
        self.assertIn("Gtk.ProgressBar", widget_source)
        self.assertNotIn("Szczegóły:", page_source)
        self.assertNotIn("detail_table", page_source)

    def test_statistics_contains_chart_and_table_separators(self) -> None:
        page_source = (self.root / "sesyjka" / "pages" / "statistics.py").read_text(
            encoding="utf-8"
        )
        app_source = (self.root / "sesyjka" / "app.py").read_text(encoding="utf-8")
        self.assertIn("Gtk.Separator", page_source)
        self.assertIn("statistics-section-separator", page_source)
        self.assertIn("statistics-table-separator", page_source)
        self.assertIn("spacing=12", page_source)
        self.assertIn(".statistics-section-separator", app_source)
        self.assertIn(".statistics-table-separator", app_source)

    def test_context_menu_actions_have_symbolic_icons(self) -> None:
        source = (self.root / "sesyjka" / "widgets.py").read_text(encoding="utf-8")
        self.assertIn("document-edit-symbolic", source)
        self.assertIn("edit-delete-symbolic", source)
        self.assertIn("Gtk.Image.new_from_icon_name", source)

    def test_wayland_desktop_icon_integration_is_installed_system_wide(self) -> None:
        app_source = (self.root / "sesyjka" / "app.py").read_text(encoding="utf-8")
        install_source = (self.root / "install-linux.sh").read_text(encoding="utf-8")
        desktop_source = (
            self.root / "data" / "io.github.zuraffpl.Sesyjka.desktop"
        ).read_text(encoding="utf-8")
        self.assertIn("Gtk.Window.set_default_icon_name(APP_ID)", app_source)
        self.assertIn("self.set_icon_name(APP_ID)", app_source)
        self.assertIn("/usr/local/share", install_source)
        self.assertIn("Icon=io.github.zuraffpl.Sesyjka", desktop_source)
        self.assertIn("StartupWMClass=io.github.zuraffpl.Sesyjka", desktop_source)
        icon_root = self.root / "data" / "icons" / "hicolor"
        for relative in (
            "scalable/apps/io.github.zuraffpl.Sesyjka.svg",
            "64x64/apps/io.github.zuraffpl.Sesyjka.png",
            "128x128/apps/io.github.zuraffpl.Sesyjka.png",
            "256x256/apps/io.github.zuraffpl.Sesyjka.png",
        ):
            self.assertTrue((icon_root / relative).is_file(), relative)

    def test_run_script_only_starts_local_source(self) -> None:
        source = (self.root / "run.sh").read_text(encoding="utf-8")
        self.assertIn('-m sesyjka "$@"', source)
        for forbidden in (
            "ensure-desktop-integration",
            "install-linux.sh",
            "/usr/local",
            "/opt/sesyjka",
            "update-desktop-database",
            "gtk4-update-icon-cache",
        ):
            self.assertNotIn(forbidden, source)

    def test_install_and_uninstall_scripts_target_system_paths(self) -> None:
        install = (self.root / "install-linux.sh").read_text(encoding="utf-8")
        uninstall = (self.root / "uninstall-linux.sh").read_text(encoding="utf-8")
        for token in ("/opt/sesyjka", "/usr/local/bin/sesyjka", "/usr/local/share"):
            self.assertIn(token, install)
            self.assertIn(token, uninstall)
        self.assertIn("--purge-data", uninstall)
        self.assertIn("XDG_DATA_HOME", uninstall)

    def test_requested_screenshot_set_is_bundled(self) -> None:
        screenshot_dir = self.root / "screenshots"
        expected = {"image.png", *(f"image{index}.png" for index in range(2, 12))}
        self.assertEqual({path.name for path in screenshot_dir.glob("*.png")}, expected)
        self.assertTrue(all((screenshot_dir / name).stat().st_size > 0 for name in expected))

    def test_source_project_basics_are_exposed(self) -> None:
        app = (self.root / "sesyjka" / "app.py").read_text(encoding="utf-8")
        sessions = (self.root / "sesyjka" / "pages" / "sessions.py").read_text(
            encoding="utf-8"
        )
        systems = (self.root / "sesyjka" / "pages" / "systems.py").read_text(
            encoding="utf-8"
        )
        transfer = (self.root / "sesyjka" / "transfer.py").read_text(encoding="utf-8")
        for token in ("show_help", "show_history", "show_transfer", "show_about"):
            self.assertIn(token, app)
        self.assertIn("Zaznacz grupę", sessions)
        self.assertIn("co najmniej jednego", sessions)
        self.assertIn("cena_zakupu", systems)
        self.assertIn("cena_sprzedazy", systems)
        self.assertIn("Eksport folderu", transfer)
        self.assertIn("Tryb gościa", transfer)

    def test_board_games_tab_and_separate_database_are_integrated(self) -> None:
        app = (self.root / "sesyjka" / "app.py").read_text(encoding="utf-8")
        config = (self.root / "sesyjka" / "config.py").read_text(encoding="utf-8")
        database = (self.root / "sesyjka" / "database_manager.py").read_text(encoding="utf-8")
        page = (self.root / "sesyjka" / "pages" / "board_games.py").read_text(encoding="utf-8")
        statistics = (self.root / "sesyjka" / "repository.py").read_text(encoding="utf-8")
        self.assertIn('"board_games": BoardGamesPage', app)
        self.assertIn('"Gry planszowe"', app)
        self.assertIn('"planszowe.db"', config)
        self.assertIn("CREATE TABLE IF NOT EXISTS planszowe", database)
        for token in ("min_graczy", "max_graczy", "czas_min", "minimalny_wiek", "status_kolekcja"):
            self.assertIn(token, page)
        self.assertIn('"Planszówki/Karcianki"', statistics)

    def test_rpg_form_contains_dynamic_prices_and_automatic_total(self) -> None:
        systems = (self.root / "sesyjka" / "pages" / "systems.py").read_text(encoding="utf-8")
        widgets = (self.root / "sesyjka" / "widgets.py").read_text(encoding="utf-8")
        for token in (
            '"Formaty"',
            '"Cena fizyczna"',
            '"Cena VTT"',
            '"Cena PDF"',
            '"Cena łączna"',
            "update_total",
            "update_visibility",
            "set_editable(False)",
            '{"Na sprzedaż", "Sprzedane"}',
        ):
            self.assertIn(token, systems)
        self.assertIn("set_row_visible", widgets)

    def test_rpg_rows_are_colored_by_collection_status(self) -> None:
        systems = (self.root / "sesyjka" / "pages" / "systems.py").read_text(encoding="utf-8")
        widgets = (self.root / "sesyjka" / "widgets.py").read_text(encoding="utf-8")
        app = (self.root / "sesyjka" / "app.py").read_text(encoding="utf-8")
        self.assertIn('record.get("status_kolekcja")', systems)
        self.assertNotIn('self._status_css(record.get("status_gra"))', systems)
        for css_class in (
            "status-collection-owned",
            "status-collection-for-sale",
            "status-collection-sold",
            "status-collection-not-owned",
            "status-collection-wishlist",
            "status-collection-loaned",
            "status-collection-mixed",
        ):
            self.assertIn(css_class, systems)
            self.assertIn(css_class, widgets)
            self.assertIn(f".{css_class}", app)

    def test_database_button_and_import_confirmation_are_semantic(self) -> None:
        app = (self.root / "sesyjka" / "app.py").read_text(encoding="utf-8")
        transfer = (self.root / "sesyjka" / "transfer.py").read_text(encoding="utf-8")
        dialogs = (self.root / "sesyjka" / "dialogs.py").read_text(encoding="utf-8")
        self.assertIn('Gtk.Button.new_from_icon_name("database")', app)
        self.assertNotIn('Gtk.Button.new_from_icon_name("document-save-symbolic")', app)
        self.assertIn('confirm_label="Zaimportuj"', transfer)
        self.assertIn('destructive=False', transfer)
        self.assertIn('confirm_label: str = "Usuń"', dialogs)
        self.assertIn('"suggested-action"', dialogs)

    def test_statistics_include_total_collection_value(self) -> None:
        page = (self.root / "sesyjka" / "pages" / "statistics.py").read_text(encoding="utf-8")
        repository = (self.root / "sesyjka" / "repository.py").read_text(encoding="utf-8")
        self.assertIn('"Wartość pozycji"', repository)
        self.assertIn('cena_zakupu', repository)
        self.assertIn('item.get("cena")', repository)
        self.assertIn('clickable = label in charts', page)

    def test_session_calendar_export_is_available_in_ics_and_csv(self) -> None:
        transfer = (self.root / "sesyjka" / "transfer.py").read_text(encoding="utf-8")
        repository = (self.root / "sesyjka" / "repository.py").read_text(encoding="utf-8")
        self.assertIn("Sesje do ICS", transfer)
        self.assertIn("Sesje do CSV", transfer)
        self.assertIn("export_sessions_ics", repository)
        self.assertIn("BEGIN:VCALENDAR", repository)
        self.assertIn("export_sessions_csv", repository)
        self.assertIn('"All Day Event"', repository)

    def test_table_backgrounds_style_real_rows_and_use_zebra_striping(self) -> None:
        widgets = (self.root / "sesyjka" / "widgets.py").read_text(encoding="utf-8")
        app = (self.root / "sesyjka" / "app.py").read_text(encoding="utf-8")
        self.assertIn('widget.get_css_name() == "row"', widgets)
        self.assertIn('widget.add_css_class(row_css_class)', widgets)
        self.assertNotIn('cell.add_css_class(row_css_class)', widgets)
        self.assertNotIn("ROW_STRIPE_CLASSES", widgets)
        self.assertIn(".data-table > listview > row:nth-child(even)", app)
        self.assertIn(".data-table > listview > row > cell", app)
        self.assertIn("background: transparent", app)
        self.assertIn("row.status-collection-owned", app)
        self.assertNotIn(".table-cell.status-collection-owned", app)

    def test_supplements_support_multiple_checkbox_subgroups(self) -> None:
        systems = (self.root / "sesyjka" / "pages" / "systems.py").read_text(encoding="utf-8")
        repository = (self.root / "sesyjka" / "repository.py").read_text(encoding="utf-8")
        for label in (
            "Scenariusz/kampania",
            "Rozwinięcie zasad",
            "Moduł",
            "Lorebook/Sourcebook",
            "Bestiariusz",
            "Starter/Zestaw Startowy",
        ):
            self.assertIn(label, systems)
        self.assertIn("supplement_checks", systems)
        self.assertIn('item_type.text() == "Suplement"', systems)
        self.assertIn('" | ".join(selected_supplement_types)', systems)
        self.assertIn('item_type.casefold() == "suplement"', repository)

    def test_language_choices_and_non_blocking_isbn_warning_are_available(self) -> None:
        systems = (self.root / "sesyjka" / "pages" / "systems.py").read_text(encoding="utf-8")
        validation = (self.root / "sesyjka" / "validation.py").read_text(encoding="utf-8")
        self.assertIn('LANGUAGE_CHOICES', systems)
        self.assertIn('("PL", "ENG", "DE", "FR", "ES", "IT", "Inny")', validation)
        self.assertIn('not is_valid_isbn(isbn_value)', systems)
        self.assertIn('confirm_label="Zapisz mimo to"', systems)
        self.assertIn('destructive=False', systems)

    def test_purchase_currency_has_common_code_hint(self) -> None:
        systems = (self.root / "sesyjka" / "pages" / "systems.py").read_text(encoding="utf-8")
        repository = (self.root / "sesyjka" / "repository.py").read_text(encoding="utf-8")
        self.assertIn("PLN, USD, EUR lub GBP", systems)
        self.assertIn("dialog-information-symbolic", systems)
        self.assertIn('currency_code == "GPB"', repository)


if __name__ == "__main__":
    unittest.main()
