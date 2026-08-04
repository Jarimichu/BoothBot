"""Posts a captured photo to Discord (webhook) and/or Telegram (bot API)."""
import requests

REQUEST_TIMEOUT = 20


def post_to_discord(photo_path, webhook_url: str) -> tuple[bool, str]:
    try:
        with open(photo_path, "rb") as f:
            resp = requests.post(
                webhook_url,
                files={"file": (photo_path.name, f, "image/jpeg")},
                timeout=REQUEST_TIMEOUT,
            )
        if resp.status_code in (200, 204):
            return True, "Discord: sent"
        return False, f"Discord: HTTP {resp.status_code} {resp.text[:200]}"
    except requests.RequestException as exc:
        return False, f"Discord: {exc}"


def post_to_telegram(photo_path, bot_token: str, chat_id: str) -> tuple[bool, str]:
    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
    try:
        with open(photo_path, "rb") as f:
            resp = requests.post(
                url,
                data={"chat_id": chat_id},
                files={"photo": (photo_path.name, f, "image/jpeg")},
                timeout=REQUEST_TIMEOUT,
            )
        if resp.status_code == 200:
            return True, "Telegram: sent"
        return False, f"Telegram: HTTP {resp.status_code} {resp.text[:200]}"
    except requests.RequestException as exc:
        return False, f"Telegram: {exc}"


def post_photo(photo_path, config):
    """Posts to every enabled destination, returning a list of (success, message) results."""
    results = []
    if config.discord_enabled:
        results.append(post_to_discord(photo_path, config.discord_webhook_url))
    if config.telegram_enabled:
        results.append(post_to_telegram(photo_path, config.telegram_bot_token, config.telegram_chat_id))
    if not results:
        results.append((False, "No upload destinations configured"))
    return results
