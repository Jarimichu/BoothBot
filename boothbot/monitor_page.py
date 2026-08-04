"""Pure HTML rendering for the remote monitoring dashboard - no sockets, easy to test standalone."""
import html
from datetime import datetime

from . import __version__

PAGE_CSS = """
:root { color-scheme: light dark; }
body { font-family: -apple-system, "Segoe UI", Arial, sans-serif; margin: 0; padding: 16px;
       background: #111; color: #eee; }
@media (prefers-color-scheme: light) { body { background: #f4f4f4; color: #111; } }
header { margin-bottom: 12px; }
.banner { display: inline-block; padding: 4px 10px; border-radius: 4px; font-weight: bold; margin-top: 4px; }
.banner.ok { background: #1E8E3C; color: white; }
.banner.warn { background: #E6A23C; color: white; }
.banner.problem { background: #C62828; color: white; }
section { margin-bottom: 16px; }
h3 { margin: 0 0 6px; font-size: 0.95em; opacity: 0.85; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 8px; }
.tile { background: rgba(128,128,128,0.15); border-radius: 6px; padding: 8px 10px; }
.tile .label { font-size: 0.75em; opacity: 0.7; }
.tile .value { font-size: 1.1em; font-weight: 600; }
.error-box { background: rgba(198,40,40,0.15); border: 1px solid #C62828; border-radius: 6px; padding: 8px 10px; }
.error-box pre { white-space: pre-wrap; word-break: break-word; margin: 4px 0 0; font-size: 0.85em; }
.chart { display: flex; align-items: flex-end; gap: 2px; height: 140px;
         border-bottom: 1px solid rgba(128,128,128,0.4); }
.chart .col { flex: 1; display: flex; flex-direction: column-reverse; height: 100%; min-width: 4px; }
.chart .seg.ok { background: #50DC64; }
.chart .seg.fail { background: #E64646; }
.axis { display: flex; justify-content: space-between; font-size: 0.7em; opacity: 0.7; margin-top: 2px; }
table { border-collapse: collapse; width: 100%; }
td, th { text-align: left; padding: 3px 8px; font-size: 0.9em; }
footer { margin-top: 16px; font-size: 0.8em; opacity: 0.7; }
a { color: inherit; }
"""


def _ago(dt) -> str:
    if dt is None:
        return "never"
    seconds = max(0, (datetime.now() - dt).total_seconds())
    if seconds < 5:
        return "just now"
    if seconds < 60:
        return f"{int(seconds)}s ago"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes}m {int(seconds % 60)}s ago"
    hours = minutes // 60
    return f"{hours}h {minutes % 60}m ago"


def render_status_panel(status: dict) -> str:
    camera_value = "OK" if status["camera_ok"] else ("Not detected" if status["camera_ok"] is False else "Unknown")
    tiles = [
        ("Camera", f"{camera_value} ({_ago(status['camera_checked_at'])})"),
        ("Booth state", status["state"]),
        ("Last photo", _ago(status["last_capture_at"])),
        ("This session", f"{status['captures_this_session']} photos, {status['failures_this_session']} failed"),
        ("Destinations", ", ".join(status["destinations"]) or "None enabled"),
        ("Consecutive failures", str(status["consecutive_failures"])),
    ]
    cells = "".join(
        f'<div class="tile"><div class="label">{html.escape(label)}</div>'
        f'<div class="value">{html.escape(value)}</div></div>'
        for label, value in tiles
    )
    return f'<section class="tiles">{cells}</section>'


def render_error_panel(status: dict) -> str:
    if not status["last_error"]:
        return ""
    at, message = status["last_error"]
    return (
        '<section class="error-box">'
        f"<strong>Last error &middot; {_ago(at)}</strong>"
        f"<pre>{html.escape(message)}</pre>"
        "</section>"
    )


def render_bar_chart(hourly: list) -> str:
    max_count = max((bucket["total"] for bucket in hourly), default=0)
    cols = []
    for hour, bucket in enumerate(hourly):
        ok = bucket["delivered"] + bucket["local"]
        fail = bucket["partial"] + bucket["failed"]
        total = ok + fail
        if max_count == 0 or total == 0:
            ok_pct = fail_pct = 0.0
        else:
            ok_pct = ok / max_count * 100
            fail_pct = fail / max_count * 100
        title = f"{hour:02d}:00 - {total} photos ({ok} ok, {fail} failed)"
        cols.append(
            f'<div class="col" title="{html.escape(title)}">'
            f'<div class="seg ok" style="height:{ok_pct:.1f}%"></div>'
            f'<div class="seg fail" style="height:{fail_pct:.1f}%"></div>'
            "</div>"
        )
    axis = "".join(f"<span>{hour:02d}</span>" for hour in range(0, 24, 3))
    return (
        "<section><h3>Photos by hour of day (all recorded history)</h3>"
        f'<div class="chart">{"".join(cols)}</div>'
        f'<div class="axis">{axis}</div></section>'
    )


def render_totals_table(totals: dict) -> str:
    rows = [f"<tr><td>Local</td><td>{totals['saved_locally']} saved</td>"
            f"<td>{totals['total'] - totals['saved_locally']} failed</td></tr>"]
    if totals["discord_attempts"]:
        rows.append(
            f"<tr><td>Discord</td><td>{totals['discord_ok']} sent</td><td>{totals['discord_failed']} failed</td></tr>"
        )
    if totals["telegram_attempts"]:
        rows.append(
            f"<tr><td>Telegram</td><td>{totals['telegram_ok']} sent</td><td>{totals['telegram_failed']} failed</td></tr>"
        )
    return (
        "<table><tr><th>Destination</th><th>Sent/Saved</th><th>Failed</th></tr>"
        + "".join(rows)
        + "</table>"
    )


def render_dashboard(status: dict, hourly: list, totals: dict, refresh_seconds: int = 10) -> str:
    refresh_tag = f'<meta http-equiv="refresh" content="{refresh_seconds}">' if refresh_seconds else ""

    if status["consecutive_failures"] >= 3:
        banner_class, banner_text = "problem", "PROBLEM"
    elif status["last_error"] is not None:
        banner_class, banner_text = "warn", "WARNING"
    else:
        banner_class, banner_text = "ok", "OK"

    updated = datetime.now().strftime("%H:%M:%S")
    running_since = status["session_started_at"].strftime("%H:%M") if status["session_started_at"] else "?"
    pause_link = (
        '<a href="/?refresh=0">pause auto-refresh</a>' if refresh_seconds else '<a href="/">resume auto-refresh</a>'
    )

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
{refresh_tag}
<title>BoothBot Monitor</title>
<style>{PAGE_CSS}</style>
</head>
<body>
<header>
  <div>BoothBot v{html.escape(__version__)} &middot; running since {html.escape(running_since)} &middot; updated {updated}</div>
  <span class="banner {banner_class}">{banner_text}</span>
</header>
{render_status_panel(status)}
{render_error_panel(status)}
{render_bar_chart(hourly)}
{render_totals_table(totals)}
<footer>{pause_link} &middot; <a href="/status.json">json</a></footer>
</body>
</html>"""
