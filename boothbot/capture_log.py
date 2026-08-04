"""Append-only CSV log of every capture attempt, read back by the setup screen's Logs tab."""
import csv
import threading
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
    "discord_message",
    "discord_attempts",
    "telegram_enabled",
    "telegram_success",
    "telegram_message",
    "telegram_attempts",
    "resolved_at",
]

# The pre-verbose-logging column set (7 fields). A log file written by an older version has this
# as its header; new rows must never be appended under it as-is, or csv.DictReader misaligns every
# column once it hits a 12-value row under a 7-name header.
LEGACY_FIELDNAMES = [
    "timestamp", "photo_file", "saved_locally", "discord_enabled", "discord_success",
    "telegram_enabled", "telegram_success",
]

TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"

HOURS_IN_DAY = 24

# Guards every read-modify-write of captures.csv. A background retry thread from a previous booth
# session can still be calling append_capture() while the setup screen concurrently calls
# delete_entry() - both read the whole file and rewrite it, so without this lock one write can
# silently clobber the other.
_file_lock = threading.Lock()


def _migrate_header_if_needed() -> None:
    """Rewrites the log file to use the current FIELDNAMES header if it's missing or stale, so a
    file that predates verbose logging (or one that already got mixed-width rows appended under a
    stale header) reads back correctly. Each row is reinterpreted by its own field count rather
    than trusting whatever header is on disk, since old- and new-format rows can be interleaved.
    Caller must hold _file_lock."""
    if not LOG_PATH.exists() or LOG_PATH.stat().st_size == 0:
        return

    with open(LOG_PATH, "r", newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if header == FIELDNAMES:
            return
        rows = list(reader)

    migrated = []
    for row in rows:
        names = FIELDNAMES if len(row) == len(FIELDNAMES) else LEGACY_FIELDNAMES
        values = dict(zip(names, row))
        migrated.append([
            values.get("timestamp", ""),
            values.get("photo_file", ""),
            values.get("saved_locally", "0"),
            values.get("discord_enabled", "0"),
            values.get("discord_success", "0"),
            values.get("discord_message", ""),
            values.get("discord_attempts", "0"),
            values.get("telegram_enabled", "0"),
            values.get("telegram_success", "0"),
            values.get("telegram_message", ""),
            values.get("telegram_attempts", "0"),
            values.get("resolved_at") or values.get("timestamp", ""),
        ])

    with open(LOG_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(FIELDNAMES)
        writer.writerows(migrated)


def append_capture(
    *,
    photo_file: str,
    saved_locally: bool,
    discord_enabled: bool,
    discord_success: bool,
    telegram_enabled: bool,
    telegram_success: bool,
    discord_message: str = "",
    discord_attempts: int = 0,
    telegram_message: str = "",
    telegram_attempts: int = 0,
    captured_at: "datetime | None" = None,
    resolved_at: "datetime | None" = None,
) -> None:
    """Appends one row to the capture log, once a capture's outcome is fully resolved (which may be up
    to several minutes after the photo was taken, if retries were needed). Never raises - a logging
    failure must not crash the booth."""
    captured_at = captured_at or datetime.now()
    resolved_at = resolved_at or captured_at
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with _file_lock:
            _migrate_header_if_needed()
            write_header = not LOG_PATH.exists() or LOG_PATH.stat().st_size == 0
            with open(LOG_PATH, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                if write_header:
                    writer.writerow(FIELDNAMES)
                writer.writerow([
                    captured_at.strftime(TIMESTAMP_FORMAT),
                    photo_file,
                    "1" if saved_locally else "0",
                    "1" if discord_enabled else "0",
                    "1" if discord_success else "0",
                    discord_message,
                    str(discord_attempts),
                    "1" if telegram_enabled else "0",
                    "1" if telegram_success else "0",
                    telegram_message,
                    str(telegram_attempts),
                    resolved_at.strftime(TIMESTAMP_FORMAT),
                ])
    except OSError as exc:
        print(f"Could not write capture log: {exc}")


def delete_entry(photo_file: str) -> bool:
    """Removes every log row referencing photo_file (normally just one). Returns True if a row was
    actually removed. Never raises - a logging problem must not crash the setup screen."""
    if not photo_file:
        return False
    try:
        with _file_lock:
            if not LOG_PATH.exists():
                return False
            _migrate_header_if_needed()
            with open(LOG_PATH, "r", newline="", encoding="utf-8") as f:
                reader = csv.reader(f)
                next(reader, None)  # header, already guaranteed current by the migration above
                rows = list(reader)

            photo_idx = FIELDNAMES.index("photo_file")
            kept = [row for row in rows if len(row) <= photo_idx or row[photo_idx] != photo_file]
            if len(kept) == len(rows):
                return False

            with open(LOG_PATH, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(FIELDNAMES)
                writer.writerows(kept)
            return True
    except OSError as exc:
        print(f"Could not delete capture log entry: {exc}")
        return False


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
                    captured_at = datetime.fromisoformat(row["timestamp"])
                    resolved_raw = row.get("resolved_at") or ""
                    entries.append({
                        "timestamp": captured_at,
                        "photo_file": row.get("photo_file", ""),
                        "saved_locally": row.get("saved_locally") == "1",
                        "discord_enabled": row.get("discord_enabled") == "1",
                        "discord_success": row.get("discord_success") == "1",
                        "discord_message": row.get("discord_message") or "",
                        "discord_attempts": int(row.get("discord_attempts") or 0),
                        "telegram_enabled": row.get("telegram_enabled") == "1",
                        "telegram_success": row.get("telegram_success") == "1",
                        "telegram_message": row.get("telegram_message") or "",
                        "telegram_attempts": int(row.get("telegram_attempts") or 0),
                        # Older rows (before verbose logging) have no resolved_at - fall back to capture time.
                        "resolved_at": datetime.fromisoformat(resolved_raw) if resolved_raw else captured_at,
                    })
                except (ValueError, TypeError, KeyError):
                    continue
    except OSError:
        return []

    return entries


def classify_entry(entry: dict) -> str:
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


def latest_status(entries: list[dict]) -> dict:
    """Derives 'how did the pipeline recently do' from the tail of the log - the setup screen's
    substitute for the live in-memory status BoothApp tracks during an active session, since
    setup has no session in progress to observe directly."""
    ordered = sorted(entries, key=lambda entry: entry["timestamp"], reverse=True)

    last_capture_at = ordered[0]["timestamp"] if ordered else None
    last_success_at = None
    last_error = None
    consecutive_failures = 0

    for entry in ordered:
        # "local" (no destinations enabled, saved fine) counts as success here too - matches
        # _finalize_capture's own all_ok definition in app.py (saved_locally and every *enabled*
        # destination succeeded), so a purely local-only booth doesn't look perpetually broken.
        if classify_entry(entry) in ("delivered", "local"):
            last_success_at = entry["resolved_at"]
            break
        consecutive_failures += 1
        if last_error is None:
            failing = []
            if not entry["saved_locally"]:
                failing.append("Local save failed")
            if entry["discord_enabled"] and not entry["discord_success"]:
                failing.append(entry["discord_message"] or "Discord: failed")
            if entry["telegram_enabled"] and not entry["telegram_success"]:
                failing.append(entry["telegram_message"] or "Telegram: failed")
            last_error = (entry["resolved_at"], "; ".join(failing) if failing else "Unknown error")

    return {
        "last_capture_at": last_capture_at,
        "last_success_at": last_success_at,
        "last_error": last_error,
        "consecutive_failures": consecutive_failures,
    }


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
        outcome = classify_entry(entry)
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


# In-memory registry of captures still being sent/retried, keyed by captured_at.isoformat().
# A capture only gets a captures.csv row once append_capture() runs, which can be up to
# UPLOAD_RETRY_WINDOW_S after the photo was taken - without this, the Logs tab would have no way
# to show a photo that's still in flight. Purely in-memory: nothing here needs to (or can) survive
# a process restart, since a restart kills the retry thread it describes anyway.
_pending_lock = threading.Lock()
_pending: dict = {}


def register_pending(
    key: str, *, photo_file: str, captured_at: datetime, saved_locally: bool,
    discord_enabled: bool, telegram_enabled: bool, deadline_at: datetime,
) -> None:
    with _pending_lock:
        _pending[key] = {
            "photo_file": photo_file,
            "captured_at": captured_at,
            "saved_locally": saved_locally,
            "discord_enabled": discord_enabled,
            "discord_attempts": 0,
            "discord_success": False,
            "discord_message": "",
            "telegram_enabled": telegram_enabled,
            "telegram_attempts": 0,
            "telegram_success": False,
            "telegram_message": "",
            "deadline_at": deadline_at,
        }


def update_pending(key: str, destination: str, *, attempts: int, success: bool, message: str) -> None:
    with _pending_lock:
        entry = _pending.get(key)
        if entry is not None:
            entry[f"{destination}_attempts"] = attempts
            entry[f"{destination}_success"] = success
            entry[f"{destination}_message"] = message


def resolve_pending(key: str) -> None:
    with _pending_lock:
        _pending.pop(key, None)


def list_pending() -> list[dict]:
    """Snapshot of captures still within their retry window, most recently captured first."""
    with _pending_lock:
        entries = [dict(entry, key=key) for key, entry in _pending.items()]
    entries.sort(key=lambda entry: entry["captured_at"], reverse=True)
    return entries
