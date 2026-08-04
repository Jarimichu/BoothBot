"""Append-only CSV log of every capture attempt, read back by the setup screen's Logs tab."""
import csv
from datetime import datetime

from .config import ROOT_DIR

LOG_DIR = ROOT_DIR / "logs"
LOG_PATH = LOG_DIR / "captures.csv"

FIELDNAMES = [
    "timestamp",
    "photo_file",
    "saved_locally",
    "discord_enabled",
    "discord_success",
    "telegram_enabled",
    "telegram_success",
]

TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"

HOURS_IN_DAY = 24


def append_capture(
    *,
    photo_file: str,
    saved_locally: bool,
    discord_enabled: bool,
    discord_success: bool,
    telegram_enabled: bool,
    telegram_success: bool,
) -> None:
    """Appends one row to the capture log. Never raises - a logging failure must not crash the booth."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        write_header = not LOG_PATH.exists() or LOG_PATH.stat().st_size == 0
        with open(LOG_PATH, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if write_header:
                writer.writerow(FIELDNAMES)
            writer.writerow([
                datetime.now().strftime(TIMESTAMP_FORMAT),
                photo_file,
                "1" if saved_locally else "0",
                "1" if discord_enabled else "0",
                "1" if discord_success else "0",
                "1" if telegram_enabled else "0",
                "1" if telegram_success else "0",
            ])
    except OSError as exc:
        print(f"Could not write capture log: {exc}")


def read_entries() -> list[dict]:
    """Reads the capture log, returning [] if it's missing or unreadable."""
    if not LOG_PATH.exists():
        return []

    entries = []
    try:
        with open(LOG_PATH, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    entries.append({
                        "timestamp": datetime.fromisoformat(row["timestamp"]),
                        "photo_file": row.get("photo_file", ""),
                        "saved_locally": row.get("saved_locally") == "1",
                        "discord_enabled": row.get("discord_enabled") == "1",
                        "discord_success": row.get("discord_success") == "1",
                        "telegram_enabled": row.get("telegram_enabled") == "1",
                        "telegram_success": row.get("telegram_success") == "1",
                    })
                except (ValueError, TypeError, KeyError):
                    continue
    except OSError:
        return []

    return entries


def _classify(entry: dict) -> str:
    outcomes = []
    if entry["discord_enabled"]:
        outcomes.append(entry["discord_success"])
    if entry["telegram_enabled"]:
        outcomes.append(entry["telegram_success"])

    if not outcomes:
        return "local" if entry["saved_locally"] else "failed"
    if all(outcomes):
        return "delivered"
    if any(outcomes):
        return "partial"
    return "failed"


def summarize(entries: list[dict]) -> tuple[list[dict], dict]:
    """Buckets entries into 24 hourly slots (delivered/local/partial/failed counts) plus overall totals."""
    hourly = [{"total": 0, "delivered": 0, "local": 0, "partial": 0, "failed": 0} for _ in range(HOURS_IN_DAY)]

    totals = {
        "total": 0,
        "saved_locally": 0,
        "discord_attempts": 0,
        "discord_ok": 0,
        "discord_failed": 0,
        "telegram_attempts": 0,
        "telegram_ok": 0,
        "telegram_failed": 0,
        "first": None,
        "last": None,
    }

    for entry in entries:
        bucket = hourly[entry["timestamp"].hour]
        outcome = _classify(entry)
        bucket["total"] += 1
        bucket[outcome] += 1

        totals["total"] += 1
        if entry["saved_locally"]:
            totals["saved_locally"] += 1
        if entry["discord_enabled"]:
            totals["discord_attempts"] += 1
            if entry["discord_success"]:
                totals["discord_ok"] += 1
            else:
                totals["discord_failed"] += 1
        if entry["telegram_enabled"]:
            totals["telegram_attempts"] += 1
            if entry["telegram_success"]:
                totals["telegram_ok"] += 1
            else:
                totals["telegram_failed"] += 1

        timestamp = entry["timestamp"]
        if totals["first"] is None or timestamp < totals["first"]:
            totals["first"] = timestamp
        if totals["last"] is None or timestamp > totals["last"]:
            totals["last"] = timestamp

    return hourly, totals
