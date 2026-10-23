"""Decides which saved photos the start page previews (and the remote monitor) may show: today's,
taken at least a little while ago, not hidden by the operator from the Logs tab, and optionally only
once they've actually gone out to Discord/Telegram - so the screen never shows a photo that the
channel doesn't."""
import threading
from datetime import datetime, timedelta
from pathlib import Path

from . import capture_log

# Photos belong to the event day they were taken on, which starts at 4 AM rather than midnight -
# a late session's 1 AM photos still count as that evening's, so the screen doesn't empty mid-party.
DAY_ROLLOVER_HOUR = 4

PHOTO_PREFIX = "booth_"
PHOTO_SUFFIX = ".jpg"
FILENAME_TIME_FORMAT = "%Y%m%d_%H%M%S"  # BoothApp._start_upload saves booth_{timestamp}.jpg

# One filename per line. Next to captures.csv rather than in config.json: hiding a photo is an
# operator action on that photo, not a setting, and shouldn't depend on "Remember these settings".
HIDDEN_PATH = capture_log.LOG_DIR / "start_screen_hidden.txt"

# Guards read-modify-write of HIDDEN_PATH - the setup screen writes it while the monitor server's
# handler threads (and the preview scanner thread) read it.
_hidden_lock = threading.Lock()


def event_day(moment: datetime):
    return (moment - timedelta(hours=DAY_ROLLOVER_HOUR)).date()


def captured_at_from_name(name: str) -> "datetime | None":
    if not (name.startswith(PHOTO_PREFIX) and name.lower().endswith(PHOTO_SUFFIX)):
        return None
    try:
        return datetime.strptime(name[len(PHOTO_PREFIX):-len(PHOTO_SUFFIX)], FILENAME_TIME_FORMAT)
    except ValueError:
        return None


def _list_photos(photos_dir) -> list:
    """(path, captured_at) for every booth photo in photos_dir, newest first."""
    photos = []
    try:
        for path in Path(photos_dir).glob(f"{PHOTO_PREFIX}*{PHOTO_SUFFIX}"):
            captured_at = captured_at_from_name(path.name)
            if captured_at is not None:
                photos.append((path, captured_at))
    except OSError:
        return []
    photos.sort(key=lambda photo: photo[1], reverse=True)
    return photos


def _read_hidden() -> set:
    """Caller must hold _hidden_lock."""
    try:
        text = HIDDEN_PATH.read_text(encoding="utf-8")
    except OSError:
        return set()
    return {line.strip() for line in text.splitlines() if line.strip()}


def hidden_photos() -> set:
    with _hidden_lock:
        return _read_hidden()


def set_hidden(photo_file: str, hidden: bool) -> bool:
    """Hides (or un-hides) one photo from the start page and monitor. Returns False if the list
    couldn't be written. Never raises - like the capture log, this must not crash the setup screen."""
    if not photo_file:
        return False
    try:
        with _hidden_lock:
            names = _read_hidden()
            if hidden == (photo_file in names):
                return True
            if hidden:
                names.add(photo_file)
            else:
                names.discard(photo_file)
            HIDDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
            HIDDEN_PATH.write_text("".join(f"{name}\n" for name in sorted(names)), encoding="utf-8")
        return True
    except OSError as exc:
        print(f"Could not update the hidden photo list: {exc}")
        return False


def _uploaded_names() -> set:
    """Photos that count as posted: any enabled destination succeeded, or none were enabled when it
    was taken (classify_entry's "local") - a booth with uploads off still gets previews. A photo still
    mid-retry counts as soon as one destination succeeds, rather than once the slowest one resolves
    (its captures.csv row only appears then, which for Telegram can be many minutes later)."""
    names = {
        entry["photo_file"]
        for entry in capture_log.read_entries()
        if entry["photo_file"] and capture_log.classify_entry(entry) in ("delivered", "partial", "local")
    }
    for entry in capture_log.list_pending():
        if entry["discord_success"] or entry["telegram_success"]:
            names.add(entry["photo_file"])
    return names


def eligible_photos(photos_dir, *, delay_s: int, uploaded_only: bool, now: "datetime | None" = None) -> list:
    """(path, captured_at) for every photo the start page may show right now, newest first."""
    now = now or datetime.now()
    today = event_day(now)
    ready_before = now - timedelta(seconds=max(0, delay_s))
    hidden = hidden_photos()
    photos = [
        (path, captured_at)
        for path, captured_at in _list_photos(photos_dir)
        if event_day(captured_at) == today and captured_at <= ready_before and path.name not in hidden
    ]
    if uploaded_only and photos:
        uploaded = _uploaded_names()
        photos = [photo for photo in photos if photo[0].name in uploaded]
    return photos


def sample_photos(photos_dir, limit: int) -> list:
    """The newest photos of any day (still skipping hidden ones) - for the setup screen's preview
    when nothing from today is eligible yet, so the layout can still be judged with real photos."""
    hidden = hidden_photos()
    return [photo for photo in _list_photos(photos_dir) if photo[0].name not in hidden][:limit]
