from __future__ import annotations

from typing import Any

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from ..dialogs import info
from ..repository import Repository
from ..widgets import DataTable, QuantityBarChart


class StatisticsPage(Gtk.Box):
    def __init__(self, parent_window: Gtk.Window, repository: Repository) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.parent_window = parent_window
        self.add_css_class("content-page")
        self.repository = repository
        self.set_margin_top(16)
        self.set_margin_bottom(16)
        self.set_margin_start(16)
        self.set_margin_end(16)
        self._data: dict[str, Any] = {}
        self._selected_chart = "Pozycje RPG"
        self._card_buttons: dict[str, Gtk.Button] = {}

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        title = Gtk.Label(label="Podsumowanie", xalign=0.0)
        title.add_css_class("title-2")
        title.set_hexpand(True)
        top.append(title)
        refresh = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        refresh.set_tooltip_text("Odśwież statystyki")
        refresh.connect("clicked", lambda _button: self.refresh())
        top.append(refresh)
        self.append(top)

        self.cards = Gtk.FlowBox()
        self.cards.set_selection_mode(Gtk.SelectionMode.NONE)
        self.cards.set_max_children_per_line(6)
        self.cards.set_min_children_per_line(2)
        self.cards.set_column_spacing(10)
        self.cards.set_row_spacing(10)
        self.append(self.cards)

        vertical = Gtk.Paned.new(Gtk.Orientation.VERTICAL)
        vertical.set_vexpand(True)

        summary_paned = Gtk.Paned.new(Gtk.Orientation.HORIZONTAL)
        summary_paned.set_size_request(-1, 230)
        systems_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        systems_heading = Gtk.Label(label="Sesje według systemu", xalign=0.0)
        systems_heading.add_css_class("heading")
        systems_box.append(systems_heading)
        self.systems_table = DataTable(
            (("System", "name"), ("Sesje", "count")),
            expand_column=0,
            enable_filters=False,
        )
        systems_box.append(self.systems_table)

        players_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        players_heading = Gtk.Label(label="Udział graczy", xalign=0.0)
        players_heading.add_css_class("heading")
        players_box.append(players_heading)
        self.players_table = DataTable(
            (("Gracz", "name"), ("Sesje", "count")),
            expand_column=0,
            enable_filters=False,
        )
        players_box.append(self.players_table)
        summary_paned.set_start_child(systems_box)
        summary_paned.set_end_child(players_box)
        summary_paned.set_position(620)
        vertical.set_start_child(summary_paned)

        chart_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        separator.add_css_class("statistics-section-separator")
        separator.set_tooltip_text("Rozdzielacz zestawień i wykresu")
        chart_section.append(separator)

        self.chart = QuantityBarChart()
        chart_section.append(self.chart)
        vertical.set_end_child(chart_section)
        vertical.set_position(280)
        self.append(vertical)

    def set_read_only(self, _value: bool) -> None:
        return

    def _clear_cards(self) -> None:
        child = self.cards.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            self.cards.remove(child)
            child = next_child
        self._card_buttons.clear()

    def _build_card(self, label: str, value: int) -> Gtk.Button:
        button = Gtk.Button()
        button.add_css_class("stat-card-button")
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        content.add_css_class("stat-card")
        number = Gtk.Label(label=str(value))
        number.add_css_class("title-1")
        caption = Gtk.Label(label=label)
        caption.add_css_class("dim-label")
        content.append(number)
        content.append(caption)
        button.set_child(content)
        button.set_tooltip_text(f"Pokaż wykres ilości: {label}")
        button.connect("clicked", lambda _button, selected=label: self.show_chart(selected))
        return button

    def show_chart(self, label: str) -> None:
        chart = self._data.get("charts", {}).get(label)
        if not chart:
            return
        self._selected_chart = label

        for card_label, button in self._card_buttons.items():
            if card_label == label:
                button.add_css_class("suggested-action")
            else:
                button.remove_css_class("suggested-action")

        self.chart.set_data(str(chart["title"]), list(chart["items"]))

    def refresh(self) -> None:
        try:
            self._data = self.repository.statistics()
            self._clear_cards()
            for label, value in self._data["counts"].items():
                button = self._build_card(label, int(value))
                self._card_buttons[label] = button
                self.cards.append(button)
            self.systems_table.set_records(
                [{"name": name, "count": count} for name, count in self._data["systems"]]
            )
            self.players_table.set_records(
                [{"name": name, "count": count} for name, count in self._data["players"]]
            )
            if self._selected_chart not in self._data.get("charts", {}):
                self._selected_chart = "Pozycje RPG"
            self.show_chart(self._selected_chart)
        except Exception as exc:
            info(self.parent_window, "Błąd statystyk", str(exc), error=True)
