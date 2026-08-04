"""Posts a captured photo to Discord (webhook) and/or Telegram (bot API)."""
from typing import NamedTuple

import requests

REQUEST_TIMEOUT = 20
TEST_MESSAGE = "BoothBot test message - this destination is configured correctly."

DESTINATION_LABELS = {"discord": "Discord", "telegram": "Telegram", "local": "Local"}


class UploadResult(NamedTuple):
    destination: str  # "discord" | "telegram" | "local"
    success: bool
    message: str


def _post(destination, url, ok_statuses, success_message="sent", **kwargs) -> UploadResult:
    label = DESTINATION_LABELS[destination]
    try:
        resp = requests.post(url, timeout=REQUEST_TIMEOUT, **kwargs)
    except requests.RequestException as exc:
        return UploadResult(destination, False, f"{label}: {exc}")
    if resp.status_code in ok_statuses:
        return UploadResult(destination, True, f"{label}: {success_message}")
    return UploadResult(destination, False, f"{label}: HTTP {resp.status_code} {resp.text[:200]}")


def post_to_discord(photo_path, webhook_url: str) -> UploadResult:
    with open(photo_path, "rb") as f:
        return _post(
            "discord", webhook_url, (200, 204),
            files={"file": (photo_path.name, f, "image/jpeg")},
        )


def post_to_telegram(photo_path, bot_token: str, chat_id: str) -> UploadResult:
    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
    with open(photo_path, "rb") as f:
        return _post(
            "telegram", url, (200,),
            data={"chat_id": chat_id},
            files={"photo": (photo_path.name, f, "image/jpeg")},
        )


def test_discord(webhook_url: str) -> UploadResult:
    return _post(
        "discord", webhook_url, (200, 204),
        success_message="test message sent",
        json={"content": TEST_MESSAGE},
    )


def test_telegram(bot_token: str, chat_id: str) -> UploadResult:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    return _post(
        "telegram", url, (200,),
        success_message="test message sent",
        data={"chat_id": chat_id, "text": TEST_MESSAGE},
    )


def post_photo(photo_path, config) -> list[UploadResult]:
    """Posts to every enabled destination, returning a list of UploadResults."""
    results = []
    if config.discord_enabled:
        results.append(post_to_discord(photo_path, config.discord_webhook_url))
    if config.telegram_enabled:
        results.append(post_to_telegram(photo_path, config.telegram_bot_token, config.telegram_chat_id))
    if not results:
        results.append(UploadResult("local", False, "No upload destinations configured"))
    return results
