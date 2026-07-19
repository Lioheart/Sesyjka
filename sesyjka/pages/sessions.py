from __future__ import annotations

from datetime import date
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from ..dialogs import ModalWindow, info, make_entry
from ..repository import Repository
from ..widgets import Choice, ChoiceDropDown, FormGrid, TextDropDown
from .base import CrudPage


class SessionsPage(CrudPage):
    def __init__(self, parent_window: Gtk.Window, repository: Repository) -> None:
        super().__init__(
            parent_window,
            repository,
            (
                ("ID", "id"),
                ("Data", "data_sesji"),
                ("System", "system_nazwa"),
                ("MG", "mg_nazwa"),
                ("Gracze", "gracze_nazwy"),
                ("Liczba", "liczba_graczy"),
                ("Tryb", "tryb_gry"),
                ("Kampania", "tytul_kampanii"),
                ("Przygoda", "tytul_przygody"),
            ),
            "sesję",
        )

    def load_records(self) -> list[dict[str, Any]]:
        return self.repository.sessions()

    def delete_record(self, record_id: int) -> None:
        self.repository.delete_session(record_id)

    def describe_record(self, record: dict[str, Any]) -> str:
        return f"{record.get('data_sesji', '')}, {record.get('system_nazwa', '')}"

    def open_editor(self, record: dict[str, Any] | None) -> None:
        systems = self.repository.game_systems()
        if not systems:
            info(
                self.parent_window,
                "Brak systemów",
                "Najpierw dodaj system RPG przyciskiem „Dodaj system gry” w zakładce Systemy RPG.",
            )
            return
        players = self.repository.players()
        if not players:
            info(
                self.parent_window,
                "Brak graczy",
                "Sesja musi mieć co najmniej jednego gracza. Najpierw dodaj gracza w zakładce Gracze.",
            )
            return

        dialog = ModalWindow(
            self.parent_window,
            "Edytuj sesję" if record else "Dodaj sesję",
            width=700,
            height=780,
        )
        form = FormGrid()
        session_date = make_entry(
            record.get("data_sesji") if record else date.today().isoformat(),
            "RRRR-MM-DD",
        )
        system_choices = [Choice(int(row["id"]), str(row["nazwa"])) for row in systems]
        selected_system_id = record.get("system_id") if record else system_choices[0].identifier
        system = ChoiceDropDown(system_choices, selected_system_id)
        gm_choices = [Choice(None, "Brak, sesja GM-less"), *[Choice(int(row["id"]), str(row["nick"])) for row in players]]
        gm = ChoiceDropDown(gm_choices, record.get("mg_id") if record else None)
        mode = TextDropDown(
            ["Stacjonarnie", "Online", "Hybrydowo", "Na wydarzeniu", "Inny"],
            str(record.get("tryb_gry") or "Stacjonarnie") if record else "Stacjonarnie",
        )
        campaign = Gtk.CheckButton(label="Sesja kampanii")
        campaign.set_active(bool(record and record.get("kampania")))
        one_shot = Gtk.CheckButton(label="Jednostrzał")
        one_shot.set_active(bool(record and record.get("jednostrzal")))
        campaign_title = make_entry(record.get("tytul_kampanii") if record else "", "Tytuł kampanii")
        adventure_title = make_entry(record.get("tytul_przygody") if record else "", "Tytuł przygody")
        form.add_row("Data *", session_date)
        form.add_row("System *", system)
        form.add_row("Mistrz gry", gm)
        form.add_row("Tryb gry", mode)
        form.add_full(campaign)
        form.add_full(one_shot)
        form.add_row("Kampania", campaign_title)
        form.add_row("Przygoda", adventure_title)

        players_frame = Gtk.Frame(label="Gracze, wymagany co najmniej jeden")
        players_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        selected_ids = set(record.get("player_ids", [])) if record else set()
        player_checks: list[tuple[int, Gtk.CheckButton]] = []
        player_groups: dict[int, set[str]] = {}
        available_groups: set[str] = set()
        for player in players:
            label = str(player["nick"])
            groups = {
                item.strip()
                for item in str(player.get("grupa") or "").split(",")
                if item.strip()
            }
            player_groups[int(player["id"])] = groups
            available_groups.update(groups)
            if groups:
                label += f"  [{', '.join(sorted(groups, key=str.casefold))}]"
            check = Gtk.CheckButton(label=label)
            check.set_active(int(player["id"]) in selected_ids)
            players_list.append(check)
            player_checks.append((int(player["id"]), check))

        if available_groups:
            group_selector = TextDropDown(
                ["Wybierz grupę", *sorted(available_groups, key=str.casefold)],
                "Wybierz grupę",
            )
            select_group = Gtk.Button(label="Zaznacz grupę")
            group_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            group_selector.set_hexpand(True)
            group_row.append(group_selector)
            group_row.append(select_group)

            def select_player_group(_button: Gtk.Button) -> None:
                selected_group = group_selector.text()
                if selected_group == "Wybierz grupę":
                    return
                for player_id, check in player_checks:
                    if selected_group in player_groups.get(player_id, set()):
                        check.set_active(True)

            select_group.connect("clicked", select_player_group)
            form.add_row("Szybki wybór grupy", group_row)
        player_scroller = Gtk.ScrolledWindow()
        player_scroller.set_min_content_height(150)
        player_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        player_scroller.set_child(players_list)
        players_frame.set_child(player_scroller)
        form.add_full(players_frame)

        notes = Gtk.TextView()
        notes.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        notes.set_size_request(-1, 130)
        notes_buffer = notes.get_buffer()
        notes_buffer.set_text(str(record.get("notatka") or "") if record else "")
        notes_frame = Gtk.Frame(label="Notatki")
        notes_frame.set_child(notes)
        form.add_full(notes_frame)
        dialog.add_scrolled_content(form)

        def save() -> None:
            selected_player_ids = [
                player_id
                for player_id, check in player_checks
                if check.get_active()
            ]
            if not selected_player_ids:
                info(
                    dialog,
                    "Brak graczy",
                    "Zaznacz co najmniej jednego gracza. Sesji bez graczy nie można zapisać.",
                    error=True,
                )
                return
            start = notes_buffer.get_start_iter()
            end = notes_buffer.get_end_iter()
            note = notes_buffer.get_text(start, end, True)
            try:
                self.repository.save_session(
                    {
                        "data_sesji": session_date.get_text(),
                        "system_id": system.identifier(),
                        "mg_id": gm.identifier(),
                        "tryb_gry": mode.text(),
                        "kampania": campaign.get_active(),
                        "jednostrzal": one_shot.get_active(),
                        "tytul_kampanii": campaign_title.get_text(),
                        "tytul_przygody": adventure_title.get_text(),
                        "player_ids": selected_player_ids,
                        "notatka": note,
                    },
                    int(record["id"]) if record else None,
                )
                dialog.close()
                self.refresh()
                self.notify_data_changed()
            except Exception as exc:
                info(dialog, "Błąd zapisu", str(exc), error=True)

        dialog.add_buttons(save)
        dialog.present()
