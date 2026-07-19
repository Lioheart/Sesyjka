from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

APP_DIR_NAME = "sesyjka"
DB_FILES = ("systemy_rpg.db", "sesje_rpg.db", "gracze.db", "wydawcy.db")


def data_dir() -> Path:
    override = os.environ.get("SESYJKA_DATA_DIR")
    if override:
        path = Path(override).expanduser()
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
        path = base / APP_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_dir() -> Path:
    override = os.environ.get("SESYJKA_CONFIG_DIR")
    if override:
        path = Path(override).expanduser()
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        path = base / APP_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def state_dir() -> Path:
    override = os.environ.get("SESYJKA_STATE_DIR")
    if override:
        path = Path(override).expanduser()
    else:
        base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
        path = base / APP_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_path() -> Path:
    return config_dir() / "settings.json"


def load_settings() -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "dark_mode": False,
        "font_scale": 1.0,
        "width": 1280,
        "height": 800,
        "maximized": False,
        "check_updates": True,
        "last_update_check": 0,
    }
    try:
        loaded = json.loads(settings_path().read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            defaults.update(loaded)
    except (OSError, ValueError, TypeError):
        pass
    return defaults


def save_settings(settings: dict[str, Any]) -> None:
    target = settings_path()
    temporary = target.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(target)


def migrate_legacy_databases() -> list[tuple[Path, Path]]:
    """Kopiuje stare bazy do katalogu XDG, bez usuwania oryginałów."""
    destination = data_dir()
    legacy_dirs = [Path.home() / ".sesyjka", Path.cwd()]
    migrated: list[tuple[Path, Path]] = []
    for filename in DB_FILES:
        target = destination / filename
        if target.exists():
            continue
        for legacy_dir in legacy_dirs:
            source = legacy_dir / filename
            if source.is_file():
                shutil.copy2(source, target)
                migrated.append((source, target))
                break
    return migrated
