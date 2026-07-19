from __future__ import annotations

from collections.abc import Callable
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk


class ModalWindow(Adw.Window):
    def __init__(self, parent: Gtk.Window, title: str, width: int = 520, height: int = 520) -> None:
        super().__init__(title=title, transient_for=parent, modal=True)
        self.set_default_size(width, height)
        self.set_hide_on_close(False)

        shell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        header = Adw.HeaderBar()
        shell.append(header)

        self.root_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.root_box.set_margin_top(18)
        self.root_box.set_margin_bottom(18)
        self.root_box.set_margin_start(18)
        self.root_box.set_margin_end(18)
        self.root_box.set_vexpand(True)
        shell.append(self.root_box)
        self.set_content(shell)

    def add_scrolled_content(self, child: Gtk.Widget) -> None:
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)
        scroller.set_child(child)
        self.root_box.append(scroller)

    def add_buttons(
        self,
        on_save: Callable[[], None],
        save_label: str = "Zapisz",
    ) -> None:
        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        buttons.set_halign(Gtk.Align.END)
        cancel = Gtk.Button(label="Anuluj")
        cancel.connect("clicked", lambda _button: self.close())
        save = Gtk.Button(label=save_label)
        save.add_css_class("suggested-action")
        save.connect("clicked", lambda _button: on_save())
        buttons.append(cancel)
        buttons.append(save)
        self.root_box.append(buttons)
        self.set_default_widget(save)


def info(parent: Gtk.Window, title: str, message: str, error: bool = False) -> None:
    dialog = ModalWindow(parent, title, width=460, height=220)
    label = Gtk.Label(label=message, wrap=True, xalign=0.0)
    label.set_vexpand(True)
    if error:
        label.add_css_class("error")
    dialog.root_box.append(label)
    button = Gtk.Button(label="OK")
    button.set_halign(Gtk.Align.END)
    button.add_css_class("suggested-action")
    button.connect("clicked", lambda _button: dialog.close())
    dialog.root_box.append(button)
    dialog.set_default_widget(button)
    dialog.present()


def confirm(parent: Gtk.Window, title: str, message: str, callback: Callable[[], None]) -> None:
    dialog = ModalWindow(parent, title, width=460, height=230)
    label = Gtk.Label(label=message, wrap=True, xalign=0.0)
    label.set_vexpand(True)
    dialog.root_box.append(label)
    buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    buttons.set_halign(Gtk.Align.END)
    cancel = Gtk.Button(label="Anuluj")
    delete = Gtk.Button(label="Usuń")
    delete.add_css_class("destructive-action")
    cancel.connect("clicked", lambda _button: dialog.close())

    def accepted(_button: Gtk.Button) -> None:
        dialog.close()
        callback()

    delete.connect("clicked", accepted)
    buttons.append(cancel)
    buttons.append(delete)
    dialog.root_box.append(buttons)
    dialog.present()


def get_entry(entry: Gtk.Entry) -> str:
    return entry.get_text().strip()


def make_entry(value: Any = "", placeholder: str = "") -> Gtk.Entry:
    entry = Gtk.Entry()
    entry.set_text("" if value is None else str(value))
    if placeholder:
        entry.set_placeholder_text(placeholder)
    return entry
