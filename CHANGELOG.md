# Changelog

All notable changes to BoothBot are documented in this file.

## [Unreleased]

## [1.10.0] - 2026-10-23

### Added
- **Built-in updates from GitHub.** When the setup screen opens, BoothBot asks GitHub in the background whether a newer release is out, and the bottom of the window shows the answer. Offline, it just says it couldn't check, with nothing in red. **Check for Updates** asks again. When there's a newer version, **Update...** shows its release notes, and **Download and Install** downloads the new `BoothBot.exe` with a progress bar while setup keeps working. The download is checked against the SHA-256 checksum GitHub publishes for the file, put in place of the running exe, and BoothBot offers to restart into it.
  - Settings, photos and logs are untouched, and the exe keeps its name and folder, so "Start BoothBot when Windows starts" and any shortcuts keep working. Changes made on the setup screen before restarting are saved first, the same way Start Photobooth saves them.
  - Nothing is ever installed without a click, and nothing is checked during the photobooth or when started with Windows. Starting the photobooth or quitting during a download cancels it. **Check GitHub for a newer version when this screen opens** (General tab, on by default) turns off the automatic check.
  - From source, **Update...** shows the release notes and links to the release instead. Update with `git pull`.
  - This works from 1.10.0 onward. Copies of 1.9.0 and older have to be replaced by hand one last time.

## [1.9.0] - 2026-10-23

### Added
- **Photo previews on the start page** (Start Page tab, off by default). Photos taken earlier today are shown around the logo, so an idle booth has something to catch the eye of people walking past. Everything is configurable:
  - **Layout**: a filmstrip along the bottom, columns either side of the logo, a scatter of tilted polaroid prints (each with the time it was taken written underneath), or a dimmed, blurred full-screen background slideshow.
  - **Motion**: only what suits the chosen layout is offered. Static (newest first), rotate (one photo swaps for another every few seconds), scroll (filmstrip and columns: a continuous ticker), or a gentle drift (polaroids bob slightly). Rotating and scrolling mostly show recent photos, with older ones from the day mixed in now and then.
  - **Photos shown** (per-layout default), **Frame** for the filmstrip and columns (white border, thin border with a soft halo, or rounded corners; a dark drop shadow wouldn't show on the black background), and **Speed** (slow/medium/fast).
  - A newly eligible photo pops in and glows for a few seconds, so people notice their shot arrive.
  - With nothing to show yet (first thing in the morning), the start page looks exactly as it did before. When the first photo arrives, the screen briefly dips to black and comes back with the new layout, so the logo never visibly jumps.
- Which photos appear is deliberately conservative, since this puts guests' photos on a public screen:
  - **Today's only.** "Today" starts at 4 AM rather than midnight, so a late-night session doesn't empty the screen at 12:00.
  - **Only after a short wait** (Wait (seconds), 60 by default), so a photo doesn't pop up as that group walks away.
  - **Only once posted** (on by default): a photo appears once at least one enabled destination has it, so the start page never shows a photo that isn't already in the channel. One destination is enough, because Telegram often reports a failure for a photo it actually delivered, and requiring both would keep such photos off the screen for good. A photo still being retried counts as soon as one destination succeeds. Photos taken with both destinations turned off always count, so previews still work for an offline booth.
  - **Hide from Start Page** in the Logs tab's Overview hides a single photo without deleting it, and shows which photos are hidden. Hidden photos are kept in `logs/start_screen_hidden.txt`, not in `config.json`: hiding is an action on a photo, not a setting, so it doesn't depend on "Remember these settings". Deleting a photo also removes it from that list.
- A live **preview of the start page** at the bottom of the Start Page tab, drawn by the same code as the booth at the booth screen's proportions. It updates as you change any setting. When no photos from today can be shown yet, it uses the most recent photos as samples so the layout can still be judged.
- **Show today's photos on the monitor page** (General tab, off by default, because the page has no login). With it on, the remote monitor shows thumbnails of the newest photos the start page may show, with the same rules. Only photos on that list are ever served, so a hidden photo, one from another day, or any other file can't be fetched by guessing its name.

### Changed
- Releases are published by hand, without GitHub Actions. The automatic release workflow added in 1.7.3 had been deleted before 1.8.0; it was briefly restored and is now removed for good, so publishing a release doesn't depend on Actions minutes. The exe attached to a release is the one built and tested locally. Its helper scripts are back and still do the checks: `check_version.py` makes sure the tag matches the app's version, and `extract_release_notes.py` pulls that version's section of this changelog for the release notes. The README has a new Releases section with the steps.

## [1.8.0] - 2026-10-23

### Added
- Camera resolution setting: a **Resolution** dropdown under the camera picker (4K, 1440p, 1080p, 720p, or 640 × 480). It defaults to **1920 × 1080 (16:9)** - previously no resolution was ever set, so every camera opened in its 640 × 480 (4:3) default and every photo came out 4:3. Photos are taken at this size. A camera that can't do the requested size gets its nearest mode instead; the status line under the preview shows the size actually being used, plus "(asked for ...)" when it differs (e.g. a Logitech BRIO answers a 4K request with 1080p over DirectShow).
- **Camera Settings...** button next to it, which opens the camera driver's own settings window - exposure, white balance, focus, zoom, brightness and whatever else that camera supports - while the preview keeps running behind it. The changes are made in the camera itself rather than saved by BoothBot, so they carry over into the photobooth session but may reset if the camera is unplugged or the PC restarts.
- **Start BoothBot when Windows starts** (General tab). It adds BoothBot to the current user's Windows startup apps (the per-user Run registry key - no admin rights needed, and it shows up in Task Manager's "Startup apps" too), launching it with `--autostart`, which skips the setup screen and goes straight into the photobooth with the saved settings. It waits up to a minute for the saved camera (found by name) to come online after sign-in; if the camera never appears or won't open, setup is shown instead of an error, so whoever's there can see what's wrong. The quit key still returns to setup as usual. It runs when Windows signs in - for a booth that's simply powered on, turn on automatic sign-in in Windows as well. The checkbox applies immediately, and notices if a different copy of BoothBot (e.g. an older build in another folder) is the one registered.
- **Keep the PC and screen awake while BoothBot is open** (General tab, on by default). An unattended booth gets no mouse or keyboard input between guests, so Windows' idle timers could put it to sleep or blank the screen mid-event, which also stopped the remote monitor and any photo still uploading in the background. BoothBot now asks Windows to stay awake with the screen on the whole time it's open, on the setup screen and in the photobooth. It's the same request a video player makes: no admin rights needed, and Windows' own power settings aren't changed. They apply again as soon as BoothBot closes, even if it crashes. It can't stop a laptop from sleeping when its lid is closed. The checkbox applies immediately and is saved like any other setting. Previously only the fullscreen photobooth kept the screen on (pygame does that by default), and the setup screen didn't. With the checkbox off, Windows' own sleep and screen-off settings now apply everywhere, including the photobooth.

### Changed
- Cameras are now opened in MJPG at a fixed 30 fps, in the one property order that works across the cameras tested (FPS, then size, then format - setting FPS last silently dropped a BRIO to 5 fps uncompressed). This is what makes 1080p and up run at full frame rate. Opening a camera that way takes several seconds, so it now happens in the background: the setup screen stays responsive and says "Opening ..." (Windows no longer flags it "Not Responding" while a camera opens), the camera controls are disabled until it's ready, and Start Photobooth waits for it. The fullscreen view shows "Starting camera..." instead of a blank screen.
- Live view and photo review are much cheaper at high resolutions: frames are scaled to the screen size with OpenCV before drawing (a 4K camera on a 1080p screen ~3 ms per frame instead of ~22 ms; a 1080p camera on a 4K screen ~5 ms instead of ~18 ms), and the review photo is prepared once per capture instead of every frame. The setup preview is now 16:9 to match.

### Fixed
- If the camera fails to deliver a frame at the moment a photo is taken (e.g. it was unplugged), that capture is now logged as failed. Previously the previous group's photo was still in memory, so it was saved again under a new name, posted to Discord/Telegram again, and shown on the review screen as if it were the new photo.
- The setup window no longer stretches several thousand pixels wide while there's no camera image to show (e.g. with no camera connected) - the preview was sized in text characters rather than pixels until its first frame arrived.
- The setup screen's camera dropdown now lists cameras by name (e.g. "Logitech BRIO") instead of a bare index 0-5, so there's no more guessing which number is which device. Names are read straight from Windows' DirectShow device list - the same list, in the same order, that the camera itself is opened from - so no new dependency was added. Identical webcams are numbered ("Logitech C920 (2)") so they can still be told apart. **Refresh** now also re-scans for cameras, so one plugged in after setup opened shows up without restarting. If names can't be read for some reason, the dropdown falls back to "Camera 0"-"Camera 5".
- The chosen camera is now remembered by name as well as index (new `camera_name` setting). Camera indices shift whenever any camera is added or removed - including virtual ones like OBS's or Elgato's, which commonly take index 0 and push a real webcam to 1 - so setup now re-selects the saved camera wherever it ends up. If the saved camera isn't connected at all, setup shows the camera at the old index as a stand-in, says so under the preview, and asks before starting the photobooth with it. Existing configs without a saved name keep using their saved index.

## [1.7.3] - 2026-08-04

### Added
- Releases are now built and published automatically: pushing a `vX.Y.Z` git tag triggers a GitHub Actions workflow that builds `BoothBot.exe` on a clean Windows runner and publishes a GitHub Release with the exe attached, using the matching section of this changelog as the release notes. It also checks the tag against `boothbot/__init__.py`'s version first and fails before building if they don't match, to catch a forgotten version bump.

## [1.7.2] - 2026-08-04

### Changed
- Telegram photo uploads now wait up to 10 minutes for a response (up from 20 seconds) instead of giving up and retrying. Telegram's `sendPhoto` can take several minutes to actually complete even though the photo does eventually go through - the old short timeout meant we usually stopped listening before Telegram ever answered, misreporting a real (if slow) success as a failure. A patient single attempt is also safer than the old short-timeout-plus-retry approach, which risked reposting a photo that was going to succeed anyway. Discord and the "Send Test Message" buttons are unaffected - both still fail fast at 20 seconds.

## [1.7.1] - 2026-08-04

### Added
- The remote monitor now runs while the setup screen is open too, not just during the live photobooth session - useful for checking the dashboard from a phone while setting up, or right after a session ends if a photo is still retrying in the background. It reports camera status, recent capture history (read back from the log, since there's no live session to observe directly), and the same "still sending" panel as during a live session.

### Changed
- The General tab's monitor URL note no longer says "(only reachable while the photobooth is running)" - it's reachable as soon as setup opens.

## [1.7.0] - 2026-08-04

### Added
- The Logs tab is now split into Overview / Discord / Telegram sub-tabs, for tracking each destination's delivery separately instead of only as a combined view. Overview keeps the hourly chart (both destinations) and a simplified "Every Photo" table (captured time / filename / local-save status / state) for browsing and deleting any photo. Discord and Telegram each get their own table - only photos where that destination was enabled, with that destination's own status, attempt count, and failure reason - plus a short "N sent, N failed" summary. "Delete Selected Photo" works independently in every sub-tab.
- The remote monitor dashboard now shows a "N photos still sending" panel whenever a capture is mid-retry, with the soonest one's remaining time before it gives up - previously a photo stuck retrying for up to 15 minutes looked identical to one that had already resolved. Also included in `/status.json` for external tooling.

### Changed
- Per-destination rows in the new Discord/Telegram sub-tabs are colored by that destination's own outcome, not the combined Overview classification - a photo that failed on Telegram no longer shows ambiguously in the Discord tab just because Telegram also failed.

## [1.6.0] - 2026-08-04

### Added
- Logs tab now has an "Every Photo" table listing every capture individually - captured time, filename, local-save status, and per-destination status (sent/failed with attempt count and reason). Still-retrying photos appear first, highlighted, with a live "time still listening" countdown, ahead of the most recent resolved ones.
- "Delete Selected Photo" button in that table - removes the photo from `photos/` and its row from the log, with a confirmation prompt first. Only available for resolved photos (a still-retrying one must finish first, since its file may still be read by the background retry).
- "Telegram send retries" setting in the Photo Storage tab (default **0**). Telegram occasionally reports a failure even after the photo was actually delivered (a lost response, not a lost photo); the previous unconditional retry behavior would then repost it, causing duplicates in the channel. Telegram now sends once by default and only retries if this is raised - Discord's retry behavior (unaffected by this setting) is unchanged.

### Fixed
- A capture log file written before verbose logging was introduced (v1.5.1) had a stale, narrower header; new rows kept getting appended under it, which silently misaligned every column when the log was read back. The log now migrates its header automatically the first time it's written to after upgrading.

## [1.5.1] - 2026-08-04

### Changed
- Removed the "Sending your photo..."/"Thank you!" screens entirely - the photo review is now the last thing guests see, and the upload happens silently in the background afterward. A destination that fails is retried automatically (only that destination, never one that already succeeded, so guests are never double-posted) roughly once a minute for up to 15 minutes before giving up. This also fixes the case where an intermittent network issue made a genuinely successful send look like a failure to guests; that status remains fully visible to the operator via the Logs tab and the remote monitor.
- The capture log is now written only once a photo's outcome is fully resolved (success, final failure, or the 15-minute retry window elapsing) instead of moments after the shutter, so it always reflects the true final result. Each entry is more verbose too: per-destination status message and attempt count, plus both the captured and resolved timestamps.
- "Show the monitor URL on the start page" now defaults to off - the setup screen remains the normal way to find it, so guests at the booth don't see it unless you turn it on.
- Removed the "Result display (seconds)" setting from the Post View tab, since there's no longer a result screen for it to time.

### Removed
- `config.example.json` - no longer needed, since a missing `config.json` was always able to fall back to the built-in defaults anyway. `BoothBot.spec` no longer bundles it.

## [1.5.0] - 2026-08-04

### Added
- Remote monitoring dashboard: BoothBot now hosts a small read-only web page (stdlib `http.server` only, no new dependency) reachable on the local network while the fullscreen booth is running - live status (camera health, booth state, time since last photo, consecutive failures, most recent error) plus the same hourly photo chart as the setup screen's Logs tab, auto-refreshing every 10 seconds.
- New "Remote Monitor" section in the General tab: enable/disable, port, a "Show the monitor URL on the start page" toggle, and a URL preview with a Copy button so it can be found before the booth even starts.
- The monitor URL is shown small and dim in the corner of the fullscreen start page (when enabled) as confirmation the server actually started.

### Changed
- The server starts and stops with the fullscreen booth session only - it's never running while the setup screen is open, and binding failures (e.g. a busy port) can never take the booth down, falling back through nearby ports automatically.

## [1.4.0] - 2026-08-04

### Added
- "Send Test Message" buttons for Discord and Telegram in the Photo Storage tab, so credentials can be verified working (a real test message is posted) before the first real event photo, without needing to enable the destination first.
- New Logs tab: a capture log (`logs/captures.csv`) records every photo attempt with timestamp, local-save status, and per-destination success/failure; the tab shows a bar chart of photo counts by hour of day (color-coded: delivered / saved locally only / partly delivered / failed), a summary of totals, and a Refresh button.

### Changed
- `post_photo`'s results are now attributed by destination name (`UploadResult`) instead of positionally, fixing a latent class of bug where results could be mismatched to the wrong destination.
- A failed local photo save is no longer silently reported as "Saved locally" - `camera.save_frame` now reports whether the write actually succeeded.
- Refactored the two near-identical result-handling code paths in the booth's state machine into one shared method, which is also now the single place the capture log is written.

## [1.3.1] - 2026-08-04

### Fixed
- "Post to Discord" / "Post to Telegram" now genuinely default to off in the underlying config defaults, matching the setup screen's checkboxes.

### Changed
- Repo housekeeping: `photos/` is now fully gitignored (previously only `.jpg`/`.png` inside it were), and the tracked `.gitkeep` placeholder was removed since the app already recreates the folder automatically at startup.

## [1.3.0] - 2026-08-04

### Added
- Setup screen: "Photo Review" and "Result" tabs merged into a single "Post View" tab; "Discord & Telegram" renamed to "Photo Storage" and reorganized around a "Local Storage" section (shows the photos folder path with an **Open Folder** button) followed by independent "Post to Discord" / "Post to Telegram" enable checkboxes - both off by default, so you can hold saved credentials without posting until you're ready.
- "Scale review photo to 75%" now defaults to on.

### Changed
- Photos are always saved locally regardless of whether Discord/Telegram are enabled (this was already true, but is now surfaced clearly): if both are disabled, the result screen shows "Saved!" instead of an error, and no network request is attempted.
- Fixed the result screen's success/failure detection, which previously guessed by checking for the word "sent" in the status message rather than using the actual upload result.

## [1.2.0] - 2026-08-04

### Added
- Setup screen reorganized into tabs (General, Start Page, Live View, Photo Review, Result, Discord & Telegram) instead of one long scrolling list, with General moved first.
- Dropdown selectors: camera index, and countdown/photo review/result display seconds are now Comboboxes with common preset values (still editable for custom values).
- "Remember these settings for next time" checkbox in the General tab, checked by default - uncheck it to try settings for the current run only without overwriting `config.json`.

### Changed
- Pressing the quit key in the fullscreen view now returns to the setup screen (pre-filled with your last settings) instead of closing the program entirely. Closing the window outright (e.g. Alt+F4), or clicking Quit in the setup screen, still exits.

## [1.1.1] - 2026-08-04

### Added
- "Scale review photo to 75%" setting: when enabled, the captured photo is shrunk to 75% of the screen and centered during the review, uploading, and result phases, so the top/bottom review messages sit clearly above and below it instead of overlapping.

## [1.1.0] - 2026-08-04

### Added
- Start page: a configurable message (default "Press button to start photobooth!") and optional logo image, shown fullscreen before the live camera view. Configurable from a new "Start Page" section in the setup screen, including a Browse/Clear logo file picker.
- Idle timeout: the live view now automatically returns to the start page after 30 seconds if no photo is taken.

### Changed
- After a completed photo session (once the result message finishes displaying), the app now returns to the start page instead of the live view.

## [1.0.2] - 2026-08-04

### Added
- Photo review phase: the captured photo is now shown by itself for a configurable number of seconds right after the flash, with the Discord/Telegram upload happening in the background at the same time instead of after.
- Configurable review message, split into separate top and bottom lines (e.g. "Thanks for coming to the con!" / "Please see your photo on the Telegram channel"), rendered smaller than the other on-screen text so the photo stays the focus.

### Changed
- Packaged `.exe` now builds directly into the project root (`pyinstaller BoothBot.spec --distpath .`) instead of PyInstaller's default `dist/` subfolder.

## [1.0.1] - 2026-08-04

### Added
- Configurable "live view message" setting - the prompt text shown fullscreen before a group presses the button is now editable from the setup screen instead of hardcoded, and wraps automatically if it's long.

## [1.0.0] - 2026-08-04

### Added
- Initial release: fullscreen kiosk photobooth - live webcam preview, button-triggered countdown, capture, and automatic upload to Discord (webhook) and/or Telegram (bot).
- Setup screen with a live camera preview and editable settings (camera index, countdown/result timers, capture/quit keys, fullscreen toggle, Discord/Telegram credentials) shown before the fullscreen view launches.
- Packaging as a standalone Windows `.exe` via PyInstaller, including a persistent `config.json`/`photos/` location next to the exe and embedded Windows file-version metadata.
