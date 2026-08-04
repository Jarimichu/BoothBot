# Changelog

All notable changes to BoothBot are documented in this file.

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
