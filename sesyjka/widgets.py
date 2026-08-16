from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any
import math

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gio, GObject, Gtk, Pango

class TableRow(GObject.Object):
    def __init__(self, record: dict[str, Any], values: Sequence[str]) -> None:
        super().__init__()
        self.record = record
        self.values = tuple(values)




class PieChartWidget(Gtk.Box):
    """Dostępny wykres kołowy z legendą i krótkim podsumowaniem.

    Widget korzysta z natywnego Gtk.DrawingArea zamiast zewnętrznych bibliotek
    wykresowych, dzięki czemu zachowuje niski koszt zależności i dobrze działa
    w motywach Adwaita. Przy większej liczbie kategorii agreguje mniej istotne
    pozycje do sekcji „Pozostałe”, żeby wykres pozostawał czytelny.
    """

    _MAX_VISIBLE_SLICES = 8
    _PALETTE: tuple[tuple[float, float, float], ...] = (
        (0.18, 0.49, 0.20),
        (0.11, 0.53, 0.89),
        (0.77, 0.32, 0.24),
        (0.51, 0.24, 0.86),
        (0.95, 0.61, 0.07),
        (0.00, 0.62, 0.58),
        (0.89, 0.29, 0.56),
        (0.38, 0.43, 0.46),
    )

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add_css_class("chart-shell")
        self.set_vexpand(True)
        self.set_hexpand(True)

        self.heading = Gtk.Label(xalign=0.0)
        self.heading.add_css_class("title-3")
        self.append(self.heading)

        self.summary = Gtk.Label(xalign=0.0)
        self.summary.add_css_class("dim-label")
        self.summary.set_wrap(True)
        self.append(self.summary)

        self.stack = Gtk.Stack()
        self.stack.set_vexpand(True)
        self.append(self.stack)

        self.empty = Gtk.Label(label="Brak danych do wyświetlenia", xalign=0.0)
        self.empty.add_css_class("dim-label")
        self.empty.set_margin_top(24)
        self.stack.add_named(self.empty, "empty")

        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        content.set_vexpand(True)
        self.stack.add_named(content, "content")

        chart_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        chart_box.set_halign(Gtk.Align.CENTER)
        chart_box.set_valign(Gtk.Align.CENTER)
        content.append(chart_box)

        self.drawing = Gtk.DrawingArea()
        self.drawing.set_content_width(280)
        self.drawing.set_content_height(280)
        self.drawing.set_size_request(280, 280)
        self.drawing.set_hexpand(False)
        self.drawing.set_vexpand(False)
        self.drawing.set_draw_func(self._draw_chart)
        chart_box.append(self.drawing)

        self.legend_scroller = Gtk.ScrolledWindow()
        self.legend_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.legend_scroller.set_hexpand(True)
        self.legend_scroller.set_vexpand(True)
        self.legend_scroller.set_min_content_width(320)
        content.append(self.legend_scroller)

        self.legend_rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.legend_rows.set_margin_top(4)
        self.legend_rows.set_margin_bottom(4)
        self.legend_scroller.set_child(self.legend_rows)

        self._items: list[tuple[str, float]] = []
        self._total = 0.0
        self._original_category_count = 0
        self._value_suffix = ""
        self._decimals = 0
        self._summary_note = ""

    def set_data(
        self,
        title: str,
        items: Sequence[tuple[str, Any]],
        *,
        value_suffix: str = "",
        decimals: int = 0,
        summary_note: str = "",
    ) -> None:
        normalized: list[tuple[str, float]] = []
        for label, raw_value in items:
            try:
                value = float(raw_value)
            except (TypeError, ValueError):
                continue
            if value > 0:
                normalized.append((str(label), value))
        self._value_suffix = value_suffix.strip()
        self._decimals = max(int(decimals), 0)
        self._summary_note = summary_note.strip()
        self.heading.set_text(title)
        self._original_category_count = len(normalized)
        self._items = self._compress_items(normalized)
        self._total = sum(value for _label, value in self._items)

        child = self.legend_rows.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            self.legend_rows.remove(child)
            child = next_child

        if not self._items:
            self.summary.set_text("Brak danych.")
            self.drawing.set_tooltip_text("Brak danych do wyświetlenia")
            self.stack.set_visible_child_name("empty")
            return

        self.stack.set_visible_child_name("content")
        largest_label, largest_value = max(self._items, key=lambda item: item[1])
        percent = (largest_value / self._total) * 100 if self._total else 0.0
        grouped = self._original_category_count - len(self._items)
        grouped_text = f" Zgrupowano {grouped} mniejsze kategorie." if grouped > 0 else ""
        total_text = self._format_value(self._total)
        largest_text = self._format_value(largest_value)
        note_text = f" {self._summary_note}" if self._summary_note else ""
        self.summary.set_text(
            f"Łącznie: {total_text}. Kategorie: {self._original_category_count}. "
            f"Największy udział: {largest_label} ({largest_text}, {percent:.1f}%)."
            f"{grouped_text}{note_text}"
        )

        tooltip_lines: list[str] = []
        for index, (label_text, value) in enumerate(self._items):
            share = (value / self._total) * 100 if self._total else 0.0
            color = self._color_for(index)
            formatted_value = self._format_value(value)
            tooltip_lines.append(f"{label_text}: {formatted_value} ({share:.1f}%)")
            self.legend_rows.append(self._build_legend_row(index, color, label_text, value, share))
        self.drawing.set_tooltip_text("\n".join(tooltip_lines))
        self.drawing.queue_draw()

    def _compress_items(self, items: list[tuple[str, float]]) -> list[tuple[str, float]]:
        if len(items) <= self._MAX_VISIBLE_SLICES:
            return items
        head = list(items[: self._MAX_VISIBLE_SLICES - 1])
        tail = items[self._MAX_VISIBLE_SLICES - 1 :]
        other_total = sum(value for _label, value in tail)
        if other_total > 0:
            head.append((f"Pozostałe ({len(tail)})", other_total))
        return head

    def _build_legend_row(
        self,
        index: int,
        color: tuple[float, float, float],
        label_text: str,
        value: float,
        share: float,
    ) -> Gtk.Widget:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        row.add_css_class("chart-row")

        swatch = Gtk.DrawingArea()
        swatch.set_content_width(14)
        swatch.set_content_height(14)
        swatch.set_draw_func(self._draw_swatch, color)
        row.append(swatch)

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text_box.set_hexpand(True)
        label = Gtk.Label(label=label_text, xalign=0.0)
        label.set_wrap(True)
        label.set_tooltip_text(label_text)
        label.add_css_class("chart-legend-label")
        meta = Gtk.Label(label=f"{share:.1f}%", xalign=0.0)
        meta.add_css_class("dim-label")
        text_box.append(label)
        text_box.append(meta)
        row.append(text_box)

        count = Gtk.Label(label=self._format_value(value), xalign=1.0)
        count.add_css_class("chart-count")
        row.append(count)
        return row

    def _format_value(self, value: float) -> str:
        if self._decimals <= 0:
            number = f"{int(round(value)):,}".replace(",", " ")
        else:
            number = f"{value:,.{self._decimals}f}".replace(",", " ").replace(".", ",")
        return f"{number} {self._value_suffix}".strip()

    def _draw_swatch(
        self,
        _area: Gtk.DrawingArea,
        cr: Any,
        width: int,
        height: int,
        color: tuple[float, float, float],
    ) -> None:
        radius = min(width, height) / 5
        cr.set_source_rgb(*color)
        cr.new_path()
        cr.arc(width / 2, height / 2, max(radius * 2, 2), 0, math.tau)
        cr.fill()

    def _draw_chart(self, _area: Gtk.DrawingArea, cr: Any, width: int, height: int) -> None:
        if not self._items or self._total <= 0:
            return
        radius = max(min(width, height) * 0.38, 16)
        center_x = width / 2
        center_y = height / 2
        start_angle = -math.pi / 2
        for index, (_label, value) in enumerate(self._items):
            slice_angle = math.tau * (value / self._total)
            if slice_angle <= 0:
                continue
            cr.new_path()
            cr.move_to(center_x, center_y)
            cr.arc(center_x, center_y, radius, start_angle, start_angle + slice_angle)
            cr.close_path()
            cr.set_source_rgb(*self._color_for(index))
            cr.fill_preserve()
            cr.set_source_rgba(1.0, 1.0, 1.0, 0.92)
            cr.set_line_width(2.0)
            cr.stroke()
            start_angle += slice_angle

    def _color_for(self, index: int) -> tuple[float, float, float]:
        return self._PALETTE[index % len(self._PALETTE)]


class QuantityBarChart(Gtk.Box):
    """Natywny, dostępny wykres słupkowy oparty na widgetach GTK4.

    Zastosowanie Gtk.ProgressBar zamiast osadzonego Matplotlib zachowuje
    motyw Adwaita, skalowanie tekstu i obsługę czytników ekranu bez
    dodatkowych zależności binarnych.
    """

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add_css_class("chart-shell")
        self.set_vexpand(True)
        self.set_hexpand(True)

        self.heading = Gtk.Label(xalign=0.0)
        self.heading.add_css_class("title-3")
        self.append(self.heading)

        self.summary = Gtk.Label(xalign=0.0)
        self.summary.add_css_class("dim-label")
        self.append(self.summary)

        self.scroller = Gtk.ScrolledWindow()
        self.scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroller.set_vexpand(True)
        self.rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.rows.set_margin_top(4)
        self.rows.set_margin_bottom(4)
        self.scroller.set_child(self.rows)
        self.append(self.scroller)

    def set_data(self, title: str, items: Sequence[tuple[str, int]]) -> None:
        normalized = [(str(label), max(int(value), 0)) for label, value in items]
        self.heading.set_text(title)
        total = sum(value for _label, value in normalized)
        self.summary.set_text(
            f"Łącznie: {total}. Kategorie: {len(normalized)}." if normalized else "Brak danych."
        )

        child = self.rows.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            self.rows.remove(child)
            child = next_child

        if not normalized:
            empty = Gtk.Label(label="Brak danych do wyświetlenia", xalign=0.0)
            empty.add_css_class("dim-label")
            empty.set_margin_top(24)
            self.rows.append(empty)
            return

        maximum = max((value for _label, value in normalized), default=0)
        for label_text, value in normalized:
            row = Gtk.Grid(column_spacing=12)
            row.add_css_class("chart-row")
            row.set_hexpand(True)

            label = Gtk.Label(label=label_text, xalign=0.0)
            label.set_width_chars(22)
            label.set_max_width_chars(34)
            label.set_ellipsize(Pango.EllipsizeMode.END)
            label.set_tooltip_text(label_text)

            bar = Gtk.ProgressBar()
            bar.set_hexpand(True)
            bar.set_fraction((value / maximum) if maximum > 0 else 0.0)
            bar.set_tooltip_text(f"{label_text}: {value}")

            count = Gtk.Label(label=str(value), xalign=1.0)
            count.add_css_class("chart-count")

            row.attach(label, 0, 0, 1, 1)
            row.attach(bar, 1, 0, 1, 1)
            row.attach(count, 2, 0, 1, 1)
            self.rows.append(row)


class DataTable(Gtk.Box):
    """Tabela GTK4 z sortowaniem, filtrami kolumnowymi i menu kontekstowym.

    W trybie ``grouped`` rekordy nadrzędne powinny zawierać ``_is_group=True``
    oraz listę rekordów potomnych w polu ``_children``. Grupy są rozwijane i
    zwijane po aktywacji wiersza. Sortowanie w tym trybie odbywa się osobno dla
    grup oraz dla elementów wewnątrz każdej grupy, dzięki czemu hierarchia nie
    zostaje rozbita.
    """

    def __init__(
        self,
        columns: Sequence[tuple[str, str]],
        expand_column: int = 1,
        *,
        grouped: bool = False,
        tree_key: str = "nazwa",
        enable_filters: bool = True,
        enable_sorting: bool = True,
        link_columns: dict[str, str] | None = None,
        boolean_icon_columns: dict[str, str] | None = None,
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.columns = list(columns)
        self.grouped = grouped
        self.tree_key = tree_key
        self.enable_filters = enable_filters
        self.enable_sorting = enable_sorting
        self.link_columns = dict(link_columns or {})
        self.boolean_icon_columns = dict(boolean_icon_columns or {})
        self.add_css_class("data-table-shell")

        self._source_records: list[dict[str, Any]] = []
        self._global_filter = ""
        self._column_filters: dict[str, str] = {}
        self._collapsed_groups: set[str] = set()
        self._visible_count = 0
        self._total_count = 0
        self._activate_callback: Callable[[dict[str, Any]], None] | None = None
        self._edit_callback: Callable[[dict[str, Any]], None] | None = None
        self._delete_callback: Callable[[dict[str, Any]], None] | None = None
        self._view_changed_callback: Callable[[], None] | None = None
        self._read_only = False
        self._filter_entries: dict[str, Gtk.Entry] = {}

        self.store = Gio.ListStore.new(TableRow)
        self.view = Gtk.ColumnView.new(None)
        self.view.set_hexpand(True)
        self.view.set_vexpand(True)
        self.view.set_show_row_separators(True)
        self.view.set_show_column_separators(True)
        self.view.add_css_class("data-table")

        if grouped:
            self.selection = Gtk.SingleSelection.new(self.store)
            self.view.set_model(self.selection)
        else:
            sorter = self.view.get_sorter() if enable_sorting else None
            self.sort_model = Gtk.SortListModel.new(self.store, sorter)
            self.selection = Gtk.SingleSelection.new(self.sort_model)
            self.view.set_model(self.selection)

        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        controls.set_margin_top(6)
        controls.set_margin_start(6)
        controls.set_margin_end(6)

        if enable_filters:
            self.filter_button = Gtk.MenuButton(label="Filtry kolumnowe")
            self.filter_button.set_tooltip_text("Filtruj niezależnie każdą kolumnę")
            self.filter_button.set_popover(self._build_filter_popover())
            controls.append(self.filter_button)

            clear_filters = Gtk.Button.new_from_icon_name("edit-clear-all-symbolic")
            clear_filters.set_tooltip_text("Wyczyść filtry kolumnowe")
            clear_filters.connect("clicked", lambda _button: self.clear_column_filters())
            controls.append(clear_filters)

        if grouped and enable_sorting:
            sort_label = Gtk.Label(label="Sortuj według")
            sort_label.add_css_class("dim-label")
            controls.append(sort_label)
            self.sort_dropdown = Gtk.DropDown(
                model=Gtk.StringList.new([title for title, _key in self.columns])
            )
            self.sort_dropdown.set_selected(1 if len(self.columns) > 1 else 0)
            self.sort_dropdown.connect("notify::selected", lambda *_args: self._rebuild_store())
            controls.append(self.sort_dropdown)

            self.sort_direction = Gtk.ToggleButton()
            self.sort_direction.set_icon_name("view-sort-descending-symbolic")
            self.sort_direction.set_tooltip_text("Zmień kierunek sortowania")
            self.sort_direction.connect("toggled", self._on_sort_direction_toggled)
            controls.append(self.sort_direction)
        elif enable_sorting:
            hint = Gtk.Label(label="Kliknij nagłówek kolumny, aby sortować")
            hint.add_css_class("dim-label")
            hint.set_hexpand(True)
            hint.set_halign(Gtk.Align.END)
            controls.append(hint)

        if controls.get_first_child() is not None:
            self.append(controls)

        for index, (title, key) in enumerate(self.columns):
            factory = Gtk.SignalListItemFactory()
            factory.connect("setup", self._setup_cell, index)
            factory.connect("bind", self._bind_cell, index)
            column = Gtk.ColumnViewColumn.new(title, factory)
            column.set_resizable(True)
            column.set_expand(index == expand_column)
            if enable_sorting and not grouped:
                column.set_sorter(Gtk.CustomSorter.new(self._compare_rows, key))
            self.view.append_column(column)

        self.view.connect("activate", self._on_activate)

        self.scroller = Gtk.ScrolledWindow()
        self.scroller.add_css_class("data-table-scroller")
        self.scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.scroller.set_child(self.view)
        self.append(self.scroller)
        self._pinned_refresh_view_state: tuple[tuple[str, str] | None, float, float] | None = None

    def pin_refresh_view_state(self) -> None:
        """Zapamiętaj viewport przed otwarciem modala lub operacją CRUD.

        Zamknięcie okna modalnego może spowodować relayout rodzica zanim kod
        odświeży model tabeli. Wtedy bieżące GtkAdjustment bywa już ustawione na
        początek. Jawny snapshot wykonany przed modalem eliminuje ten wyścig.
        """
        self._pinned_refresh_view_state = self._capture_refresh_view_state()

    def _build_filter_popover(self) -> Gtk.Popover:
        popover = Gtk.Popover()
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        outer.set_margin_top(12)
        outer.set_margin_bottom(12)
        outer.set_margin_start(12)
        outer.set_margin_end(12)
        heading = Gtk.Label(label="Filtry kolumnowe", xalign=0.0)
        heading.add_css_class("heading")
        outer.append(heading)

        grid = Gtk.Grid(column_spacing=10, row_spacing=8)
        for row_index, (title, key) in enumerate(self.columns):
            label = Gtk.Label(label=title, xalign=0.0)
            entry = Gtk.Entry()
            entry.set_placeholder_text("Zawiera...")
            entry.set_hexpand(True)
            entry.connect("changed", self._on_column_filter_changed, key)
            self._filter_entries[key] = entry
            grid.attach(label, 0, row_index, 1, 1)
            grid.attach(entry, 1, row_index, 1, 1)
        outer.append(grid)
        popover.set_child(outer)
        return popover

    def _setup_cell(self, _factory: Gtk.SignalListItemFactory, item: Gtk.ListItem, index: int) -> None:
        cell = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        cell.set_hexpand(True)
        cell.set_vexpand(True)
        cell.add_css_class("table-cell")

        key = self.columns[index][1]
        if key in self.link_columns:
            content: Gtk.Widget = Gtk.LinkButton.new_with_label("about:blank", "")
            content.set_hexpand(True)
            content.set_halign(Gtk.Align.START)
            content.add_css_class("table-link")
        elif key in self.boolean_icon_columns:
            content = Gtk.Image.new_from_icon_name("window-close-symbolic")
            content.set_halign(Gtk.Align.CENTER)
            content.set_valign(Gtk.Align.CENTER)
            content.add_css_class("boolean-status-icon")
        else:
            label = Gtk.Label(xalign=0.0)
            label.set_hexpand(True)
            label.set_ellipsize(Pango.EllipsizeMode.END)
            if index == 0:
                label.add_css_class("numeric")
            content = label
        cell.append(content)

        gesture = Gtk.GestureClick()
        gesture.set_button(3)
        gesture.connect("pressed", self._on_context_pressed, item)
        cell.add_controller(gesture)
        item.set_child(cell)

    def _bind_cell(
        self,
        _factory: Gtk.SignalListItemFactory,
        item: Gtk.ListItem,
        index: int,
    ) -> None:
        row = item.get_item()
        cell = item.get_child()
        content = cell.get_first_child() if isinstance(cell, Gtk.Box) else None
        if not isinstance(row, TableRow) or not isinstance(cell, Gtk.Box):
            return

        text = row.values[index] if index < len(row.values) else ""
        key = self.columns[index][1]
        if isinstance(content, Gtk.LinkButton):
            uri_key = self.link_columns.get(key, "")
            uri = str(row.record.get(uri_key) or "")
            content.set_label(text)
            content.set_uri(uri or "about:blank")
            content.set_sensitive(bool(uri))
            content.set_tooltip_text(uri or None)
        elif isinstance(content, Gtk.Image) and key in self.boolean_icon_columns:
            group_only = bool(row.record.get("_is_group")) and not bool(
                row.record.get("_is_entity")
            )
            content.set_visible(not group_only)
            if group_only:
                content.set_tooltip_text(None)
                return
            source_key = self.boolean_icon_columns[key]
            present = bool(row.record.get(source_key))
            content.set_from_icon_name(
                "object-select-symbolic" if present else "window-close-symbolic"
            )
            content.set_tooltip_text("Jest" if present else "Brak")
            if present:
                content.add_css_class("format-present")
                content.remove_css_class("format-absent")
            else:
                content.add_css_class("format-absent")
                content.remove_css_class("format-present")
        elif isinstance(content, Gtk.Label):
            content.set_text(text)
            if row.record.get("_is_group"):
                content.add_css_class("heading")
            else:
                content.remove_css_class("heading")


    @staticmethod
    def _compare_rows(left: TableRow, right: TableRow, key: str) -> Gtk.Ordering:
        left_value = _sort_value(left.record.get(key))
        right_value = _sort_value(right.record.get(key))
        if left_value < right_value:
            return Gtk.Ordering.SMALLER
        if left_value > right_value:
            return Gtk.Ordering.LARGER
        return Gtk.Ordering.EQUAL

    def _on_sort_direction_toggled(self, button: Gtk.ToggleButton) -> None:
        descending = button.get_active()
        button.set_icon_name(
            "view-sort-ascending-symbolic" if descending else "view-sort-descending-symbolic"
        )
        self._rebuild_store()

    def _on_column_filter_changed(self, entry: Gtk.Entry, key: str) -> None:
        value = entry.get_text().strip().casefold()
        if value:
            self._column_filters[key] = value
        else:
            self._column_filters.pop(key, None)
        self._update_filter_button_label()
        self._rebuild_store()

    def _update_filter_button_label(self) -> None:
        if not hasattr(self, "filter_button"):
            return
        count = len(self._column_filters)
        self.filter_button.set_label(
            f"Filtry kolumnowe ({count})" if count else "Filtry kolumnowe"
        )

    def clear_column_filters(self) -> None:
        for entry in self._filter_entries.values():
            if entry.get_text():
                entry.set_text("")
        self._column_filters.clear()
        self._update_filter_button_label()
        self._rebuild_store()

    def set_global_filter(self, text: str) -> None:
        value = text.strip().casefold()
        if value == self._global_filter:
            return
        self._global_filter = value
        self._rebuild_store()

    @staticmethod
    def _record_identity(record: dict[str, Any] | None) -> tuple[str, str] | None:
        if record is None:
            return None
        if record.get("_is_group") and not record.get("_is_entity"):
            return ("group", DataTable._group_id(record))
        identifier = record.get("id")
        if identifier is None:
            return None
        return (str(record.get("_record_kind") or "entity"), str(identifier))

    def _capture_refresh_view_state(self) -> tuple[tuple[str, str] | None, float, float]:
        selected = self._record_identity(self.selected_record())
        horizontal = float(self.scroller.get_hadjustment().get_value())
        vertical = float(self.scroller.get_vadjustment().get_value())
        return selected, horizontal, vertical

    @staticmethod
    def _restore_adjustment(adjustment: Gtk.Adjustment, value: float) -> None:
        lower = float(adjustment.get_lower())
        upper = float(adjustment.get_upper())
        page_size = float(adjustment.get_page_size())
        maximum = max(lower, upper - page_size)
        adjustment.set_value(min(max(float(value), lower), maximum))

    def _restore_refresh_view_state(
        self,
        _widget: Gtk.Widget,
        _frame_clock: Gdk.FrameClock,
        state: tuple[tuple[str, str] | None, float, float],
    ) -> bool:
        selected_identity, horizontal, vertical = state
        if selected_identity is not None:
            for position in range(int(self.selection.get_n_items())):
                item = self.selection.get_item(position)
                if isinstance(item, TableRow) and self._record_identity(item.record) == selected_identity:
                    self.selection.set_selected(position)
                    break
        self._restore_adjustment(self.scroller.get_hadjustment(), horizontal)
        self._restore_adjustment(self.scroller.get_vadjustment(), vertical)
        return False

    def set_records(self, records: Sequence[dict[str, Any]]) -> None:
        # CRUD refreshes replace all rows in Gio.ListStore. Preserve the current
        # table viewport and selection so saving a record does not jump the user
        # back to the first row of a long collection.
        view_state = self._pinned_refresh_view_state or self._capture_refresh_view_state()
        self._pinned_refresh_view_state = None
        self._source_records = list(records)
        if self.grouped:
            valid_ids = {
                self._group_id(record)
                for record in self._walk_records(self._source_records)
                if record.get("_children")
            }
            self._collapsed_groups.intersection_update(valid_ids)
        self._rebuild_store()
        self.add_tick_callback(self._restore_refresh_view_state, view_state)

    def _rebuild_store(self) -> None:
        self.store.remove_all()
        if self.grouped:
            records = self._grouped_visible_records()
            for record in records:
                self.store.append(TableRow(record, self._values_for_record(record)))
        else:
            records = [record for record in self._source_records if self._matches(record)]
            self._visible_count = len(records)
            self._total_count = len(self._source_records)
            for record in records:
                self.store.append(TableRow(record, self._values_for_record(record)))
        if self._view_changed_callback is not None:
            self._view_changed_callback()

    def _grouped_visible_records(self) -> list[dict[str, Any]]:
        filtering = bool(self._global_filter or self._column_filters)
        sort_index = int(self.sort_dropdown.get_selected()) if hasattr(self, "sort_dropdown") else 0
        sort_index = min(max(sort_index, 0), max(len(self.columns) - 1, 0))
        sort_key = self.columns[sort_index][1] if self.columns else self.tree_key
        reverse = bool(self.sort_direction.get_active()) if hasattr(self, "sort_direction") else False

        def prune(record: dict[str, Any]) -> dict[str, Any] | None:
            children = [
                child
                for raw_child in record.get("_children", [])
                if (child := prune(raw_child)) is not None
            ]
            own_match = self._matches(record)
            if filtering and not own_match and not children:
                return None

            copy = dict(record)
            if record.get("_children"):
                # Gdy filtr pasuje do rodzica, pokazujemy także całą jego
                # podgrupę. W przeciwnym razie pozostają tylko pasujące gałęzie.
                raw_children = list(record.get("_children", []))
                copy["_children"] = raw_children if filtering and own_match else children
            else:
                copy["_children"] = []
            return copy

        roots = [
            item
            for raw_record in self._source_records
            if (item := prune(raw_record)) is not None
        ]

        def sort_tree(records: list[dict[str, Any]]) -> None:
            records.sort(key=lambda row: _sort_value(row.get(sort_key)), reverse=reverse)
            for record in records:
                children = list(record.get("_children", []))
                sort_tree(children)
                record["_children"] = children

        sort_tree(roots)

        visible: list[dict[str, Any]] = []

        def flatten(record: dict[str, Any]) -> None:
            children = list(record.get("_children", []))
            copy = dict(record)
            if children:
                group_id = self._group_id(record)
                expanded = filtering or group_id not in self._collapsed_groups
                copy["_is_group"] = True
                copy["_expanded"] = expanded
            visible.append(copy)
            if children and copy.get("_expanded"):
                for child in children:
                    flatten(child)

        for root in roots:
            flatten(root)

        all_entities = [
            record
            for record in self._walk_records(self._source_records)
            if record.get("_is_entity", not record.get("_is_group"))
        ]
        visible_entities = [
            record
            for record in visible
            if record.get("_is_entity", not record.get("_is_group"))
        ]
        self._visible_count = len(visible_entities)
        self._total_count = len(all_entities)
        return visible

    @classmethod
    def _walk_records(
        cls, records: Sequence[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for record in records:
            result.append(record)
            result.extend(cls._walk_records(list(record.get("_children", []))))
        return result

    def _matches(self, record: dict[str, Any]) -> bool:
        if self._global_filter:
            haystack = " ".join(
                str(value or "")
                for key, value in record.items()
                if not key.startswith("_")
            ).casefold()
            if self._global_filter not in haystack:
                return False
        for key, needle in self._column_filters.items():
            if needle not in format_value(record.get(key)).casefold():
                return False
        return True

    def _values_for_record(self, record: dict[str, Any]) -> list[str]:
        values: list[str] = []
        for _title, key in self.columns:
            value = format_value(record.get(key))
            if self.grouped and key == self.tree_key:
                depth = max(int(record.get("_depth", 0)), 0)
                indent = "    " * depth
                if record.get("_is_group"):
                    value = indent + ("▾ " if record.get("_expanded", True) else "▸ ") + value
                elif depth > 0:
                    value = indent + "↳ " + value
            values.append(value)
        return values

    @staticmethod
    def _group_id(record: dict[str, Any]) -> str:
        return str(record.get("_group_id") or record.get("id") or record.get("nazwa"))

    def selected_record(self) -> dict[str, Any] | None:
        item = self.selection.get_selected_item()
        return item.record if isinstance(item, TableRow) else None

    def connect_activate(self, callback: Callable[[dict[str, Any]], None]) -> None:
        self._activate_callback = callback

    def set_context_actions(
        self,
        edit_callback: Callable[[dict[str, Any]], None],
        delete_callback: Callable[[dict[str, Any]], None],
    ) -> None:
        self._edit_callback = edit_callback
        self._delete_callback = delete_callback

    def set_view_changed_callback(self, callback: Callable[[], None]) -> None:
        self._view_changed_callback = callback

    def set_read_only(self, value: bool) -> None:
        self._read_only = value

    def visible_count(self) -> int:
        return self._visible_count

    def total_count(self) -> int:
        return self._total_count

    def _on_activate(self, _view: Gtk.ColumnView, position: int) -> None:
        item = self.selection.get_item(position)
        if not isinstance(item, TableRow):
            return
        record = item.record
        if record.get("_is_group"):
            group_id = self._group_id(record)
            if group_id in self._collapsed_groups:
                self._collapsed_groups.remove(group_id)
            else:
                self._collapsed_groups.add(group_id)
            self._rebuild_store()
            return
        if self._activate_callback is not None:
            self._activate_callback(record)

    def _on_context_pressed(
        self,
        _gesture: Gtk.GestureClick,
        _press_count: int,
        x: float,
        y: float,
        list_item: Gtk.ListItem,
    ) -> None:
        position = int(list_item.get_position())
        if position < 0:
            return
        self.selection.set_selected(position)
        row = list_item.get_item()
        child = list_item.get_child()
        if not isinstance(row, TableRow) or not isinstance(child, Gtk.Widget):
            return
        record = row.record
        if record.get("_context_enabled") is False:
            return
        self._show_context_menu(child, x, y, record)

    def _show_context_menu(
        self,
        anchor: Gtk.Widget,
        x: float,
        y: float,
        record: dict[str, Any],
    ) -> None:
        popover = Gtk.Popover()
        popover.add_css_class("context-menu-popover")
        popover.set_autohide(True)
        popover.set_parent(anchor)
        popover.set_has_arrow(True)
        popover.set_pointing_to(Gdk.Rectangle(x=int(x), y=int(y), width=1, height=1))

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(6)
        box.set_margin_end(6)

        edit = self._context_action_button("document-edit-symbolic", "Edytuj")
        edit.set_sensitive(not self._read_only and self._edit_callback is not None)
        edit.connect("clicked", lambda _button: self._invoke_context(popover, self._edit_callback, record))
        box.append(edit)

        delete = self._context_action_button(
            "edit-delete-symbolic",
            "Usuń",
            destructive=True,
        )
        delete.set_sensitive(not self._read_only and self._delete_callback is not None)
        delete.connect("clicked", lambda _button: self._invoke_context(popover, self._delete_callback, record))
        box.append(delete)

        popover.set_child(box)
        popover.connect("closed", lambda widget: widget.unparent())
        popover.popup()

    @staticmethod
    def _context_action_button(
        icon_name: str,
        label_text: str,
        *,
        destructive: bool = False,
    ) -> Gtk.Button:
        button = Gtk.Button()
        button.add_css_class("flat")
        if destructive:
            button.add_css_class("destructive-action")
        button.set_halign(Gtk.Align.FILL)

        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        content.add_css_class("context-menu-content")
        content.set_halign(Gtk.Align.START)
        content.append(Gtk.Image.new_from_icon_name(icon_name))
        label = Gtk.Label(label=label_text, xalign=0.0)
        label.set_hexpand(True)
        content.append(label)
        button.set_child(content)
        return button

    @staticmethod
    def _invoke_context(
        popover: Gtk.Popover,
        callback: Callable[[dict[str, Any]], None] | None,
        record: dict[str, Any],
    ) -> None:
        popover.popdown()
        if callback is not None:
            callback(record)


def _sort_value(value: Any) -> tuple[int, Any]:
    if value is None or value == "":
        return (2, "")
    if isinstance(value, bool):
        return (0, int(value))
    if isinstance(value, (int, float)):
        return (0, value)
    text = str(value).strip()
    try:
        return (0, float(text.replace(",", ".")))
    except ValueError:
        return (1, text.casefold())


def format_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Tak" if value else "Nie"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


class FormGrid(Gtk.Grid):
    def __init__(self) -> None:
        super().__init__()
        self.set_row_spacing(10)
        self.set_column_spacing(12)
        self.set_hexpand(True)
        self._row = 0
        self._labels: dict[int, Gtk.Label] = {}

    def add_row(self, label: str, widget: Gtk.Widget) -> Gtk.Widget:
        title = Gtk.Label(label=label, xalign=0.0)
        title.set_valign(Gtk.Align.CENTER)
        widget.set_hexpand(True)
        self.attach(title, 0, self._row, 1, 1)
        self.attach(widget, 1, self._row, 1, 1)
        self._labels[id(widget)] = title
        self._row += 1
        return widget

    def set_row_visible(self, widget: Gtk.Widget, visible: bool) -> None:
        widget.set_visible(visible)
        label = self._labels.get(id(widget))
        if label is not None:
            label.set_visible(visible)

    def add_full(self, widget: Gtk.Widget) -> Gtk.Widget:
        widget.set_hexpand(True)
        self.attach(widget, 0, self._row, 2, 1)
        self._row += 1
        return widget


class Choice:
    def __init__(self, identifier: int | None, label: str) -> None:
        self.identifier = identifier
        self.label = label




def _configure_dropdown_search(dropdown: Gtk.DropDown) -> None:
    """Włącz rzeczywiste filtrowanie tekstowe w Gtk.DropDown.

    Samo ``set_enable_search(True)`` wyświetla pole wyszukiwania, ale GTK
    wymaga również wyrażenia zwracającego tekst elementu. Bez niego wpisywanie
    frazy nie filtruje listy. Dla Gtk.StringList elementami są Gtk.StringObject.
    """
    expression = Gtk.PropertyExpression.new(Gtk.StringObject, None, "string")
    dropdown.set_expression(expression)
    dropdown.set_enable_search(True)
    if hasattr(dropdown, "set_search_match_mode"):
        dropdown.set_search_match_mode(Gtk.StringFilterMatchMode.SUBSTRING)

class ChoiceDropDown(Gtk.DropDown):
    def __init__(self, choices: Sequence[Choice], selected_id: int | None = None) -> None:
        self.choices: list[Choice] = []
        super().__init__()
        _configure_dropdown_search(self)
        self.set_choices(choices, selected_id)

    def identifier(self) -> int | None:
        position = int(self.get_selected())
        if 0 <= position < len(self.choices):
            return self.choices[position].identifier
        return None

    def set_identifier(self, identifier: int | None) -> None:
        for position, choice in enumerate(self.choices):
            if choice.identifier == identifier:
                self.set_selected(position)
                return
        if self.choices:
            self.set_selected(0)

    def set_choices(self, choices: Sequence[Choice], selected_id: int | None = None) -> None:
        self.choices = list(choices)
        self.set_model(Gtk.StringList.new([choice.label for choice in self.choices]))
        self.set_selected(0 if self.choices else Gtk.INVALID_LIST_POSITION)
        self.set_identifier(selected_id)


class TextDropDown(Gtk.DropDown):
    def __init__(self, choices: Sequence[str], selected: str | None = None) -> None:
        values = list(dict.fromkeys([*choices, *([selected] if selected and selected not in choices else [])]))
        self.values = values
        super().__init__(model=Gtk.StringList.new(values))
        _configure_dropdown_search(self)
        if selected in values:
            self.set_selected(values.index(selected))

    def text(self) -> str:
        position = int(self.get_selected())
        return self.values[position] if 0 <= position < len(self.values) else ""


def set_css(css: str) -> Gtk.CssProvider:
    provider = Gtk.CssProvider()
    provider.load_from_data(css)
    display = Gdk.Display.get_default()
    if display is not None:
        Gtk.StyleContext.add_provider_for_display(
            display,
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )
    return provider
