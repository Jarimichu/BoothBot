"""Loads booth configuration from config.json (created from config.example.json on first run)."""
import json
import shutil
import sys
from pathlib import Path

# When frozen by PyInstaller (onefile), __file__ lives in a temp extraction dir that's
# wiped after every run - config.json/photos must live next to the exe instead, so user
# settings and captured photos actually persist between launches.
if getattr(sys, "frozen", False):
    ROOT_DIR = Path(sys.executable).resolve().parent
    BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", ROOT_DIR))
else:
    ROOT_DIR = Path(__file__).resolve().parent.parent
    BUNDLE_DIR = ROOT_DIR

CONFIG_PATH = ROOT_DIR / "config.json"
EXAMPLE_CONFIG_PATH = BUNDLE_DIR / "config.example.json"

DEFAULTS = {
    "camera_index": 0,
    "countdown_seconds": 5,
    "capture_key": "space",
    "quit_key": "escape",
    "fullscreen": True,
    "photos_dir": "photos",
    "post_capture_display_seconds": 4,
    "discord_webhook_url": "",
    "telegram_bot_token": "",
    "telegram_chat_id": "",
}


class Config:
    def __init__(self, data: dict):
        merged = {**DEFAULTS, **data}
        for key, value in merged.items():
            setattr(self, key, value)
        self.photos_dir = ROOT_DIR / self.photos_dir
        self.photos_dir.mkdir(parents=True, exist_ok=True)

    @property
    def discord_enabled(self) -> bool:
        return bool(self.discord_webhook_url)

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)


def load_config_dict() -> dict:
    """Reads config.json (creating it from the example/defaults if missing) as a plain dict."""
    if not CONFIG_PATH.exists():
        if EXAMPLE_CONFIG_PATH.exists():
            shutil.copy(EXAMPLE_CONFIG_PATH, CONFIG_PATH)
        else:
            CONFIG_PATH.write_text(json.dumps(DEFAULTS, indent=2))

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    return {**DEFAULTS, **data}


def save_config_dict(data: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_config() -> Config:
    return Config(load_config_dict())
