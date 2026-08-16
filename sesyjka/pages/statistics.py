from __future__ import annotations

from typing import Any

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from ..dialogs import info
from ..repository import Repository
from ..widgets import DataTable, PieChartWidget


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

        self.content_stack = Gtk.Stack()
        self.content_stack.set_hexpand(True)
        self.content_stack.set_vexpand(True)
        self.content_stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)

        switcher = Gtk.StackSwitcher()
        switcher.set_stack(self.content_stack)
        switcher.set_halign(Gtk.Align.CENTER)
        switcher.add_css_class("statistics-subtabs")
        self.append(switcher)

        charts_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        charts_page.set_hexpand(True)
        charts_page.set_vexpand(True)

        # Dziewięć kafelków ma pozostać w jednym rzędzie. Gtk.Box daje tu
        # przewidywalniejszy układ niż FlowBox, który wcześniej wymuszał
        # zawinięcie dziewiątego kafelka do drugiego wiersza.
        self.cards = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.cards.set_hexpand(True)
        charts_page.append(self.cards)

        self.chart = PieChartWidget()
        self.chart.set_vexpand(True)
        charts_page.append(self.chart)
        self.content_stack.add_titled(charts_page, "charts", "Wykresy")

        tables_page = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        tables_page.set_hexpand(True)
        tables_page.set_vexpand(True)

        systems_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        systems_box.set_hexpand(True)
        systems_box.set_vexpand(True)
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
        players_box.set_hexpand(True)
        players_box.set_vexpand(True)
        players_heading = Gtk.Label(label="Udział graczy", xalign=0.0)
        players_heading.add_css_class("heading")
        players_box.append(players_heading)
        self.players_table = DataTable(
            (("Gracz", "name"), ("Sesje", "count")),
            expand_column=0,
            enable_filters=False,
        )
        players_box.append(self.players_table)

        table_separator = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        table_separator.add_css_class("statistics-table-separator")
        tables_page.append(systems_box)
        tables_page.append(table_separator)
        tables_page.append(players_box)
        self.content_stack.add_titled(tables_page, "tables", "Sesje i gracze")

        self.append(self.content_stack)

    def set_read_only(self, _value: bool) -> None:
        return

    def _clear_cards(self) -> None:
        child = self.cards.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            self.cards.remove(child)
            child = next_child
        self._card_buttons.clear()

    def _build_card(self, label: str, value: Any, *, clickable: bool = True) -> Gtk.Button:
        button = Gtk.Button()
        button.add_css_class("stat-card-button")
        button.set_hexpand(True)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        content.add_css_class("stat-card")
        content.set_hexpand(True)
        number_text = str(value)
        number = Gtk.Label(label=number_text)
        number.set_wrap(True)
        number.set_justify(Gtk.Justification.CENTER)
        number.set_max_width_chars(22)
        number.add_css_class("title-2" if len(number_text) > 12 else "title-1")
        caption = Gtk.Label(label=label)
        caption.set_wrap(True)
        caption.set_justify(Gtk.Justification.CENTER)
        caption.add_css_class("dim-label")
        content.append(number)
        content.append(caption)
        button.set_child(content)
        if clickable:
            button.set_tooltip_text(f"Pokaż wykres kołowy: {label}")
            button.connect("clicked", lambda _button, selected=label: self.show_chart(selected))
        else:
            button.set_can_focus(False)
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

        self.chart.set_data(
            str(chart["title"]),
            list(chart["items"]),
            value_suffix=str(chart.get("unit") or ""),
            decimals=int(chart.get("decimals", 0) or 0),
            summary_note=str(chart.get("note") or ""),
        )

    def refresh(self) -> None:
        try:
            self._data = self.repository.statistics()
            self._clear_cards()
            charts = self._data.get("charts", {})
            for label, value in self._data["counts"].items():
                clickable = label in charts
                button = self._build_card(label, value, clickable=clickable)
                if clickable:
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
