# Changelog

All notable changes to BoothBot are documented in this file.

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
