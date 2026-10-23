# BoothBot
**Version 1.9.0** ([changelog](CHANGELOG.md))

Button-triggered photobooth for events - snaps a photo from a webcam after a countdown and auto-posts it to Telegram/Discord.

## Setup

1. Install [Python 3.10+](https://www.python.org/downloads/) on the Windows PC.
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Plug in the webcam, connect the PC to the TV (extend or duplicate display), and plug in the USB button (it just needs to register as a keyboard key press - no drivers required).
4. Run the app:
   ```
   python run.py
   ```
   A **setup window** opens first with a live camera preview on the left (the camera dropdown right below it lists connected cameras by name - pick one and the preview switches to it, or click **Refresh** to re-scan after plugging one in. The chosen camera is remembered by name, so it's still selected next time even if adding or removing another camera has shifted its position. Below it, **Resolution** sets the photo size - 1920 × 1080 (16:9) by default, up to 4K if the camera supports it; the line under the preview shows the size the camera is actually delivering - and **Camera Settings...** opens the camera's own settings window for exposure, white balance, focus, zoom and so on) and the rest of the settings organized into tabs on the right:
   - **General**: capture button key / quit key (click the field, then press the actual button/key you want - no need to know its name), the fullscreen toggle, and **Remember these settings for next time** (checked by default) - uncheck it to try something out for this run only without overwriting `config.json`. **Start BoothBot when Windows starts** adds BoothBot to Windows' startup apps so it opens straight into the photobooth (skipping this screen) when the PC signs in - it waits up to a minute for the saved camera, and falls back to this setup screen if the camera isn't found. For a booth that's just powered on, also turn on automatic sign-in in Windows. **Keep the PC and screen awake while BoothBot is open** (on by default) stops Windows from sleeping or turning the screen off while BoothBot is running, whether it's on this setup screen or in the photobooth. Windows' own power settings aren't changed and apply again as soon as BoothBot closes; closing a laptop's lid still puts it to sleep. Below that, **Remote Monitor**: an "Enable remote monitor" checkbox (on by default), the port it listens on, a "Show the monitor URL on the start page" checkbox (off by default - the setup screen is the normal way to find the URL, so guests don't see it), and a preview of the URL with a **Copy** button - see [Remote monitoring](#remote-monitoring) below.
   - **Start Page**: the message and optional logo shown fullscreen when the app first launches, before the live camera view (click Browse to pick a PNG/JPG for the logo, Clear to remove it). Pressing the capture button/key here moves on to the live view.
     **Photo Previews** (off by default) shows photos taken earlier today around the logo, to catch the eye of people walking past. **Layout** is a filmstrip along the bottom, columns either side, a scatter of tilted polaroid prints (with the time each was taken written underneath), or a dimmed full-screen background slideshow. **Motion** offers what suits that layout: static, rotate (one photo swaps every few seconds), scroll (filmstrip and columns), or a gentle drift (polaroids). **Photos shown**, **Frame** (white border, thin border with a soft halo, or rounded corners) and **Speed** fine-tune it. Which photos appear: only today's ("today" starts at 4 AM, so a late-night session doesn't empty the screen at midnight), only after **Wait (seconds)** has passed (60 by default, so a photo doesn't pop up as that group walks away), and, with **Only photos that posted to Discord or Telegram** (on by default), only once at least one destination has it (photos taken with both turned off always count). Hide a single photo from the Logs tab. A newly eligible photo pops in with a glow. With no photos to show yet, the start page looks exactly as it does without previews. The preview at the bottom of the tab shows the start page as it will look on the booth's screen, using the most recent photos as samples when none from today can be shown yet.
   - **Live View**: the message shown on the TV before a group presses the button, and the countdown length (a dropdown of common values - 3 to 10 seconds - but still editable if you want something else).
   - **Post View**: how long the captured photo is shown (dropdown), and the top/bottom messages overlaid on it (e.g. "Thanks for coming to the con!" / "Please see your photo on the Telegram channel"), plus the "Scale review photo to 75%" checkbox (checked by default - shrinks and centers the photo so those messages sit clearly above/below it instead of overlapping). The photo review is the last thing guests see - there's no separate "Sending.../Thank you!" screen afterward; the upload happens silently in the background.
   - **Photo Storage**: photos are always saved locally to a `photos/` folder next to the app - click **Open Folder** to see them. Below that, **Post to Discord** and **Post to Telegram** checkboxes (both off by default - turn one on once you've filled in its credentials below) let you enable/disable each destination independently without clearing its saved credentials - webhook URL (Discord channel Settings -> Integrations -> Webhooks), bot token ([@BotFather](https://t.me/BotFather)), and chat ID (`https://api.telegram.org/bot<token>/getUpdates`, or message [@userinfobot](https://t.me/userinfobot) for a personal chat). Each destination has a **Send Test Message** button (enabled once its fields are filled in) that posts a real test message, so you can confirm it actually works before the event starts instead of finding out on the first guest photo.
   - **Logs**: a record of every photo taken, kept in `logs/captures.csv` next to the app (click **Open Folder** to see it) - a bar chart of photo counts by hour of day, color-coded by outcome (delivered / saved locally only / partly delivered / failed), plus a summary of totals and per-destination success/failure counts. Click **Refresh** to pick up photos taken since the tab was last viewed. In the Overview's photo table, **Hide from Start Page** keeps a photo off the start page previews and the monitor page without deleting it (click it again, now **Show on Start Page**, to undo). Hidden photos are listed in `logs/start_screen_hidden.txt`.

   Click **Start Photobooth** to launch the fullscreen booth view (saving these to `config.json` unless you unchecked "Remember these settings"), or **Quit** to exit without starting.

Once fullscreen, press `Esc` (or whichever quit key you configured) to return to the setup screen - adjust settings and click **Start Photobooth** again, or click **Quit** there to close the program entirely.

## How it works

- **Setup screen**: a Tkinter window with a live webcam preview and a form for all booth settings; saves to `config.json` and hands off to the fullscreen view.
- **Start page**: the first thing shown fullscreen - a configurable message and optional logo, no camera feed, and optionally previews of photos taken earlier today. Pressing the button moves to the live view.
- **Live view**: shows the webcam feed fullscreen with a "press the button" prompt. Returns to the start page automatically after 30 seconds if no photo is taken.
- **Button press**: starts a countdown (big on-screen numbers).
- **Capture**: grabs a frame, flashes the screen white, and always saves the photo to `photos/` locally. If Discord and/or Telegram are enabled, that upload starts immediately in the background too.
- **Photo review**: displays the captured photo by itself for the configured number of seconds, then returns straight to the start page. This is the last thing guests see - there's no follow-up "Sending.../Thank you!" screen, and the app never reveals upload success or failure to guests. An intermittent network hiccup can make a genuinely successful send look like a failure, which would otherwise be confusing.
- **Background upload retries**: uploading to Discord/Telegram happens entirely on a background thread, decoupled from the guest-facing state machine. If a destination fails, it's retried automatically (only that destination - a destination that already succeeded is never re-sent, so guests never get double-posted) roughly once a minute for up to 15 minutes before giving up. The capture log entry is written only once every destination has either succeeded or the 15-minute window has elapsed, so the log reflects the true final outcome rather than a snapshot taken moments after the shutter. That status is visible to you, the operator, via the Logs tab and the [remote monitor](#remote-monitoring).
- **Capture log**: every photo attempt (successful or not) is appended to `logs/captures.csv` once its outcome is fully resolved - timestamp captured, timestamp resolved, whether it saved locally, and per destination: whether it succeeded, the resulting status message, and how many attempts it took. The setup screen's Logs tab reads this to show the hourly chart.

## Remote monitoring

While the fullscreen booth view is running (not during setup), BoothBot hosts a small read-only web dashboard on the local network - useful for checking on an unattended booth from a phone without walking up to it and interrupting a guest's photo.

- **Reachable only while the booth is live.** The server starts when you click Start Photobooth and stops the moment you return to setup - it's never running otherwise.
- **No login required.** It's open to anyone on the same network, so it only shows stats and status (booth state, camera health, recent errors, hourly photo counts), never webhook URLs or bot tokens. It shows no photos unless you tick **Show today's photos on the monitor page** (General tab, off by default). With that on, it shows small thumbnails of the newest photos the start page previews may show (today's, after the wait, not hidden), whether or not the previews themselves are turned on. Un-ticking it takes them off the page within a few seconds.
- **Finding the URL**: the setup screen's General tab shows it ahead of time, with a Copy button (the LAN IP is knowable before the server even starts). You can also check "Show the monitor URL on the start page" (off by default, so guests at the booth don't see it) to have it appear small and dim in the bottom-left corner of the fullscreen start page as confirmation it started. Auto-refreshes every 10 seconds (a "pause auto-refresh" link is there for reading a long error message without the page jumping).
- **Windows Firewall**: the first time something connects, Windows may prompt to allow BoothBot through the firewall on private networks - allow it, or nothing on your network will be able to load the page.
- Turn it off entirely or change the port via the General tab's Remote Monitor section.

## Packaging as a standalone .exe

Once you're happy with it, bundle it into a single .exe so the booth PC doesn't need a visible Python install:
```
pip install pyinstaller
pyinstaller BoothBot.spec --distpath .
```
This produces `BoothBot.exe` right in the project root - a single windowed (no console) file, built from the checked-in `BoothBot.spec` (`--distpath .` skips PyInstaller's default `dist/` subfolder). Copy `BoothBot.exe` to wherever you want it on the booth PC and just run it; on first launch it creates `config.json`, a `photos/` folder, and a `logs/` folder right next to itself (settings, captures, and the capture log all live beside the exe, not in a temp folder, so they persist between runs). Rerun the exe any time to reopen the setup screen and adjust settings.

To have it start automatically when the booth PC boots, put a shortcut to `BoothBot.exe` in the Windows Startup folder (`Win+R` -> `shell:startup`).

If you change the code, rebuild with `pyinstaller BoothBot.spec --distpath .` (edit `BoothBot.spec` directly if you need to change build options like the app name or icon). `BoothBot.exe` is gitignored, same as `build/` - it's a generated artifact, not source.

### Releases

Releases are published by hand with the [GitHub CLI](https://cli.github.com/) (`gh`), using the `BoothBot.exe` you built and tested yourself. Bump the version in `boothbot/__init__.py`, `version_info.txt` and the header above, add a section for it to `CHANGELOG.md`, rebuild and test the exe, then commit and push. Then tag that commit and publish:
```
python .github/scripts/check_version.py vX.Y.Z
git tag -a vX.Y.Z -m "BoothBot vX.Y.Z"
git push origin vX.Y.Z
python .github/scripts/extract_release_notes.py vX.Y.Z
gh release create vX.Y.Z BoothBot.exe --verify-tag --title "BoothBot vX.Y.Z" --notes-file release_notes.md
```
`check_version.py` stops if the tag doesn't match `boothbot/__init__.py`, so a forgotten version bump can't produce a mislabelled release. `extract_release_notes.py` writes that version's `CHANGELOG.md` section to `release_notes.md` (gitignored) for the release notes.
