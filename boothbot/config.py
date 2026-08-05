"""Loads booth configuration from config.json (created with default values on first run)."""
import json
import sys
from pathlib import Path

# When frozen by PyInstaller (onefile), __file__ lives in a temp extraction dir that's
# wiped after every run - config.json/photos must live next to the exe instead, so user
# settings and captured photos actually persist between launches.
if getattr(sys, "frozen", False):
    ROOT_DIR = Path(sys.executable).resolve().parent
else:
    ROOT_DIR = Path(__file__).resolve().parent.parent

CONFIG_PATH = ROOT_DIR / "config.json"

DEFAULTS = {
    "camera_index": 0,
    "countdown_seconds": 5,
    "capture_key": "space",
    "quit_key": "escape",
    "fullscreen": True,
    "photos_dir": "photos",
    "photo_review_seconds": 5,
    "start_message": "Press button to start photobooth!",
    "start_logo_path": "",
    "prompt_message": "Press the button to take a photo!",
    "review_message_top": "Thanks for coming to the con!",
    "review_message_bottom": "Please see your photo on the Telegram channel",
    "scale_review_photo": True,
    "font_family": "Arial",
    "font_size_message": 64,
    "discord_upload_enabled": False,
    "discord_webhook_url": "",
    "telegram_upload_enabled": False,
    "telegram_bot_token": "",
    "telegram_chat_id": "",
    "telegram_max_retries": 0,
    "monitor_enabled": True,
    "monitor_port": 8080,
    "monitor_show_url": False,
}


class Config:
    def __init__(self, data: dict):
        merged = {**DEFAULTS, **data}
        for key, value in merged.items():
            setattr(self, key, value)
        self.photos_dir = ROOT_DIR / self.photos_dir
        self.photos_dir.mkdir(parents=True, exist_ok=True)

        if self.start_logo_path:
            logo_path = Path(self.start_logo_path)
            if not logo_path.is_absolute():
                logo_path = ROOT_DIR / logo_path
            self.start_logo_path = str(logo_path)

    @property
    def discord_enabled(self) -> bool:
        return bool(self.discord_upload_enabled and self.discord_webhook_url)

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_upload_enabled and self.telegram_bot_token and self.telegram_chat_id)


def load_config_dict() -> dict:
    """Reads config.json (creating it with default values if missing) as a plain dict."""
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(json.dumps(DEFAULTS, indent=2))

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    return {**DEFAULTS, **data}


def save_config_dict(data: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_config() -> Config:
    return Config(load_config_dict())
