"""A Tkinter setup screen (with a live webcam preview) shown before the fullscreen booth view."""
import math
import os
import queue
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from . import __version__, capture_log, monitor_server, uploader
from .camera import Camera, CameraError
from .config import ROOT_DIR

PREVIEW_SIZE = (480, 360)
PREVIEW_INTERVAL_MS = 33
TEST_POLL_INTERVAL_MS = 200
CAMERA_INDEX_CHOICES = [str(i) for i in range(6)]
COUNTDOWN_CHOICES = [3, 4, 5, 6, 7, 8, 10]
PHOTO_REVIEW_CHOICES = [3, 4, 5, 6, 8, 10, 15]
TELEGRAM_RETRY_CHOICES = [0, 1, 2, 3, 5, 10]

STATUS_COLOR_IDLE = "#555555"
STATUS_COLOR_SUCCESS = "#1E8E3C"
STATUS_COLOR_FAILURE = "#C62828"

CHART_WIDTH = 540
CHART_HEIGHT = 230
CHART_PAD = {"left": 40, "right": 12, "top": 12, "bottom": 26}
CHART_Y_TICK_STEPS = (1, 2, 5, 10, 20, 25, 50, 100, 200, 500, 1000)
CHART_SEGMENTS = [  # bottom-to-top stacking order, and legend order
    ("delivered", "#50DC64", "Delivered"),
    ("local", "#8A8A8A", "Saved locally only"),
    ("partial", "#E6A23C", "Partly delivered"),
    ("failed", "#E64646", "Failed"),
]
CHART_ROW_COLORS = {"delivered": "#E9FBEC", "local": "#F0F0F0", "partial": "#FCF1DD", "failed": "#FCE9E9"}
PENDING_ROW_COLOR = "#E6F1FC"

LOG_DETAIL_LIMIT = 40  # newest resolved captures shown, on top of every still-pending one
LOG_DETAIL_REFRESH_MS = 2000  # only re-scheduled while a capture is still pending, see _refresh_logs


class SetupWindow:
    def __init__(self, config_data: dict):
        self.initial_config = config_data
        self.result = None
        self.remember_settings = True
        self.camera = None
        self._log_row_data = {}

        self._test_queue = queue.Queue()
        self._tests_in_flight = set()
        self._test_status_vars = {}
        self._test_status_labels = {}
        self._test_buttons = {}
        self._lan_ip = monitor_server.get_lan_ip()

        self.root = tk.Tk()
        self.root.title(f"BoothBot Setup v{__version__}")
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self._on_quit)

        self.camera_index_var = tk.IntVar(value=config_data.get("camera_index", 0))
        self.camera_status_var = tk.StringVar(value="")
        self.countdown_var = tk.IntVar(value=config_data.get("countdown_seconds", 5))
        self.photo_review_var = tk.IntVar(value=config_data.get("photo_review_seconds", 5))
        self.fullscreen_var = tk.BooleanVar(value=config_data.get("fullscreen", True))
        self.remember_settings_var = tk.BooleanVar(value=True)
        self.monitor_enabled_var = tk.BooleanVar(value=config_data.get("monitor_enabled", True))
        self.monitor_port_var = tk.IntVar(value=config_data.get("monitor_port", monitor_server.DEFAULT_PORT))
        self.monitor_show_url_var = tk.BooleanVar(value=config_data.get("monitor_show_url", False))
        self.monitor_url_var = tk.StringVar(value=f"http://{self._lan_ip}:{self.monitor_port_var.get()}")
        self.start_message_var = tk.StringVar(
            value=config_data.get("start_message", "Press button to start photobooth!")
        )
        self.start_logo_path_var = tk.StringVar(value=config_data.get("start_logo_path", ""))
        self.prompt_message_var = tk.StringVar(value=config_data.get("prompt_message", "Press the button to take a photo!"))
        self.review_message_top_var = tk.StringVar(
            value=config_data.get("review_message_top", "Thanks for coming to the con!")
        )
        self.review_message_bottom_var = tk.StringVar(
            value=config_data.get("review_message_bottom", "Please see your photo on the Telegram channel")
        )
        self.scale_review_photo_var = tk.BooleanVar(value=config_data.get("scale_review_photo", True))
        self.capture_key_var = tk.StringVar(value=config_data.get("capture_key", "space"))
        self.quit_key_var = tk.StringVar(value=config_data.get("quit_key", "escape"))
        self.discord_upload_enabled_var = tk.BooleanVar(value=config_data.get("discord_upload_enabled", False))
        self.discord_webhook_var = tk.StringVar(value=config_data.get("discord_webhook_url", ""))
        self.telegram_upload_enabled_var = tk.BooleanVar(value=config_data.get("telegram_upload_enabled", False))
        self.telegram_token_var = tk.StringVar(value=config_data.get("telegram_bot_token", ""))
        self.telegram_chat_id_var = tk.StringVar(value=config_data.get("telegram_chat_id", ""))
        self.telegram_max_retries_var = tk.IntVar(value=config_data.get("telegram_max_retries", 0))

        self._build_ui()
        self._open_camera(self.camera_index_var.get())
        self._update_preview()
        self._poll_test_results()

    # ---------- UI construction ----------

    def _build_ui(self):
        outer = ttk.Frame(self.root, padding=16)
        outer.grid(row=0, column=0, sticky="nsew")

        left = ttk.Frame(outer)
        left.grid(row=0, column=0, sticky="n", padx=(0, 24))

        # --- Left: camera preview ---
        ttk.Label(left, text="Camera Preview", font=("Segoe UI", 12, "bold")).grid(row=0, column=0, sticky="w")

        self.preview_label = ttk.Label(left, background="black")
        self.preview_label.grid(row=1, column=0, pady=(4, 4))
        self.preview_label.configure(width=PREVIEW_SIZE[0])

        camera_row = ttk.Frame(left)
        camera_row.grid(row=2, column=0, sticky="ew")
        ttk.Label(camera_row, text="Camera index:").pack(side="left")
        camera_combo = ttk.Combobox(
            camera_row, textvariable=self.camera_index_var, values=CAMERA_INDEX_CHOICES, width=4
        )
        camera_combo.pack(side="left", padx=(6, 6))
        camera_combo.bind("<<ComboboxSelected>>", lambda event: self._on_refresh_camera())
        ttk.Button(camera_row, text="Refresh", command=self._on_refresh_camera).pack(side="left")

        ttk.Label(left, textvariable=self.camera_status_var, foreground="#555").grid(
            row=3, column=0, sticky="w", pady=(4, 0)
        )

        # --- Right: tabbed settings ---
        notebook = ttk.Notebook(outer)
        notebook.grid(row=0, column=1, sticky="n")

        general_tab = self._add_tab(notebook, "General")
        row = 0
        row = self._add_key_capture(general_tab, row, "Capture button key:", self.capture_key_var)
        row = self._add_key_capture(general_tab, row, "Quit key:", self.quit_key_var)
        ttk.Checkbutton(general_tab, text="Fullscreen", variable=self.fullscreen_var).grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(4, 4)
        )
        row += 1
        ttk.Checkbutton(
            general_tab, text="Remember these settings for next time", variable=self.remember_settings_var
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(2, 4))
        row += 1

        ttk.Separator(general_tab, orient="horizontal").grid(row=row, column=0, columnspan=2, sticky="ew", pady=8)
        row += 1
        ttk.Label(general_tab, text="Remote Monitor", font=("Segoe UI", 11, "bold")).grid(
            row=row, column=0, columnspan=2, sticky="w"
        )
        row += 1
        ttk.Checkbutton(
            general_tab,
            text="Enable remote monitor (view live status from a phone/laptop on the same network)",
            variable=self.monitor_enabled_var,
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(2, 4))
        row += 1
        row = self._add_entry(general_tab, row, "Port:", self.monitor_port_var, width=8)
        ttk.Checkbutton(
            general_tab, text="Show the monitor URL on the start page", variable=self.monitor_show_url_var
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(2, 4))
        row += 1
        monitor_url_row = ttk.Frame(general_tab)
        monitor_url_row.grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 2))
        ttk.Label(monitor_url_row, textvariable=self.monitor_url_var, foreground="#555").pack(side="left")
        ttk.Button(monitor_url_row, text="Copy", command=self._on_copy_monitor_url).pack(side="left", padx=(8, 0))
        row += 1
        ttk.Label(general_tab, text="(only reachable while the photobooth is running)", foreground="#888").grid(
            row=row, column=0, columnspan=2, sticky="w"
        )
        row += 1

        start_tab = self._add_tab(notebook, "Start Page")
        row = 0
        row = self._add_entry(start_tab, row, "Start page message:", self.start_message_var, width=36)
        row = self._add_logo_picker(start_tab, row, "Start page logo:")

        live_tab = self._add_tab(notebook, "Live View")
        row = 0
        row = self._add_entry(live_tab, row, "Live view message:", self.prompt_message_var, width=36)
        row = self._add_combobox(live_tab, row, "Countdown (seconds):", self.countdown_var, COUNTDOWN_CHOICES)

        post_view_tab = self._add_tab(notebook, "Post View")
        row = 0
        row = self._add_combobox(post_view_tab, row, "Photo review (seconds):", self.photo_review_var, PHOTO_REVIEW_CHOICES)
        row = self._add_entry(post_view_tab, row, "Review message (top):", self.review_message_top_var, width=36)
        row = self._add_entry(post_view_tab, row, "Review message (bottom):", self.review_message_bottom_var, width=36)
        ttk.Checkbutton(
            post_view_tab,
            text="Scale review photo to 75% (room for messages above/below)",
            variable=self.scale_review_photo_var,
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(2, 4))
        row += 1

        storage_tab = self._add_tab(notebook, "Photo Storage")
        row = 0
        ttk.Label(storage_tab, text="Local Storage", font=("Segoe UI", 11, "bold")).grid(
            row=row, column=0, columnspan=2, sticky="w"
        )
        row += 1
        ttk.Label(storage_tab, text="Photos are always saved here, in addition to any destinations below.").grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(0, 4)
        )
        row += 1
        local_row = ttk.Frame(storage_tab)
        local_row.grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 4))
        ttk.Label(local_row, text=str(self._photos_dir_path()), foreground="#555").pack(side="left")
        ttk.Button(local_row, text="Open Folder", command=self._on_open_photos_folder).pack(side="left", padx=(8, 0))
        row += 1

        ttk.Separator(storage_tab, orient="horizontal").grid(row=row, column=0, columnspan=2, sticky="ew", pady=8)
        row += 1

        ttk.Checkbutton(storage_tab, text="Post to Discord", variable=self.discord_upload_enabled_var).grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(0, 4)
        )
        row += 1
        row = self._add_entry(storage_tab, row, "Discord webhook URL:", self.discord_webhook_var, width=36)
        row = self._add_test_row(storage_tab, row, "discord", "Send Test Message", self._on_test_discord)

        ttk.Separator(storage_tab, orient="horizontal").grid(row=row, column=0, columnspan=2, sticky="ew", pady=8)
        row += 1

        ttk.Checkbutton(storage_tab, text="Post to Telegram", variable=self.telegram_upload_enabled_var).grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(0, 4)
        )
        row += 1
        row = self._add_entry(storage_tab, row, "Telegram bot token:", self.telegram_token_var, width=36)
        row = self._add_entry(storage_tab, row, "Telegram chat ID:", self.telegram_chat_id_var, width=36)
        row = self._add_combobox(storage_tab, row, "Telegram send retries:", self.telegram_max_retries_var, TELEGRAM_RETRY_CHOICES)
        ttk.Label(
            storage_tab,
            text="Telegram sometimes reports a failure even after the photo was actually delivered -\n"
                 "retrying can repost it. Default (0) sends once; raise this only if photos are\n"
                 "genuinely going missing, not just showing as failed in the log.",
            foreground="#555", font=("Segoe UI", 8), justify="left",
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 4))
        row += 1
        row = self._add_test_row(storage_tab, row, "telegram", "Send Test Message", self._on_test_telegram)

        logs_tab = self._add_tab(notebook, "Logs")
        row = 0
        ttk.Label(logs_tab, text="Capture History", font=("Segoe UI", 11, "bold")).grid(
            row=row, column=0, columnspan=2, sticky="w"
        )
        row += 1
        log_row = ttk.Frame(logs_tab)
        log_row.grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 4))
        ttk.Label(log_row, text=str(capture_log.LOG_PATH), foreground="#555").pack(side="left")
        ttk.Button(log_row, text="Open Folder", command=self._on_open_log_folder).pack(side="left", padx=(8, 0))
        row += 1
        ttk.Label(logs_tab, text="Photos taken by hour of day (all recorded history).").grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(0, 4)
        )
        row += 1

        self.log_canvas = tk.Canvas(
            logs_tab, width=CHART_WIDTH, height=CHART_HEIGHT, bg="white",
            highlightthickness=1, highlightbackground="#CCCCCC",
        )
        self.log_canvas.grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 4))
        row += 1

        legend_row = ttk.Frame(logs_tab)
        legend_row.grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 8))
        for _key, color, label in CHART_SEGMENTS:
            swatch = tk.Canvas(legend_row, width=12, height=12, highlightthickness=0)
            swatch.create_rectangle(0, 0, 12, 12, fill=color, outline="")
            swatch.pack(side="left", padx=(0, 4))
            ttk.Label(legend_row, text=label, font=("Segoe UI", 8)).pack(side="left", padx=(0, 12))
        row += 1

        self.log_summary_var = tk.StringVar(value="")
        ttk.Label(logs_tab, textvariable=self.log_summary_var, justify="left").grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(0, 8)
        )
        row += 1

        ttk.Label(logs_tab, text="Every Photo", font=("Segoe UI", 11, "bold")).grid(
            row=row, column=0, columnspan=2, sticky="w"
        )
        row += 1
        ttk.Label(
            logs_tab,
            text="Still-retrying photos appear first (blue), followed by the most recent resolved ones.",
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 4))
        row += 1

        detail_frame = ttk.Frame(logs_tab)
        detail_frame.grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 8))
        columns = ("captured", "photo", "local", "discord", "telegram", "state")
        self.log_tree = ttk.Treeview(
            detail_frame, columns=columns, show="headings", height=8, selectmode="browse",
        )
        headings = {
            "captured": ("Captured", 78),
            "photo": ("Photo", 140),
            "local": ("Local", 44),
            "discord": ("Discord", 150),
            "telegram": ("Telegram", 150),
            "state": ("State", 150),
        }
        for col, (heading, width) in headings.items():
            self.log_tree.heading(col, text=heading)
            self.log_tree.column(col, width=width, minwidth=width, stretch=False, anchor="w")
        for tag, color in {**CHART_ROW_COLORS, "pending": PENDING_ROW_COLOR}.items():
            self.log_tree.tag_configure(tag, background=color)
        scrollbar = ttk.Scrollbar(detail_frame, orient="vertical", command=self.log_tree.yview)
        self.log_tree.configure(yscrollcommand=scrollbar.set)
        self.log_tree.pack(side="left")
        scrollbar.pack(side="left", fill="y")
        row += 1

        log_action_row = ttk.Frame(logs_tab)
        log_action_row.grid(row=row, column=0, columnspan=2, sticky="w")
        ttk.Button(log_action_row, text="Refresh", command=self._refresh_logs).pack(side="left")
        ttk.Button(log_action_row, text="Delete Selected Photo", command=self._on_delete_log_entry).pack(
            side="left", padx=(8, 0)
        )

        button_row = ttk.Frame(outer)
        button_row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(16, 0))
        ttk.Label(button_row, text=f"v{__version__}", foreground="#888").pack(side="left")
        ttk.Button(button_row, text="Quit", command=self._on_quit).pack(side="right", padx=(8, 0))
        ttk.Button(button_row, text="Start Photobooth", command=self._on_start).pack(side="right")

        for var in (self.discord_webhook_var, self.telegram_token_var, self.telegram_chat_id_var):
            var.trace_add("write", lambda *_args: self._sync_test_buttons())
        self.monitor_port_var.trace_add("write", lambda *_args: self._update_monitor_url_preview())
        self._sync_test_buttons()
        self._refresh_logs()

    def _update_monitor_url_preview(self):
        try:
            port = self.monitor_port_var.get()
        except tk.TclError:
            return
        self.monitor_url_var.set(f"http://{self._lan_ip}:{port}")

    def _on_copy_monitor_url(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.monitor_url_var.get())

    def _add_test_row(self, parent, row, destination, label, command):
        test_row = ttk.Frame(parent)
        test_row.grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 8))
        button = ttk.Button(test_row, text=label, command=command)
        button.pack(side="left")
        status_var = tk.StringVar(value="")
        status_label = ttk.Label(test_row, textvariable=status_var, foreground=STATUS_COLOR_IDLE, wraplength=300)
        status_label.pack(side="left", padx=(8, 0))
        self._test_buttons[destination] = button
        self._test_status_vars[destination] = status_var
        self._test_status_labels[destination] = status_label
        return row + 1

    def _add_tab(self, notebook, title):
        tab = ttk.Frame(notebook, padding=12)
        notebook.add(tab, text=title)
        return tab

    def _add_combobox(self, parent, row, label, var, values, width=8):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=3)
        ttk.Combobox(parent, textvariable=var, values=values, width=width).grid(row=row, column=1, sticky="w")
        return row + 1

    def _add_entry(self, parent, row, label, var, width=24):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=3)
        ttk.Entry(parent, textvariable=var, width=width).grid(row=row, column=1, sticky="w")
        return row + 1

    def _add_logo_picker(self, parent, row, label):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=3)
        file_row = ttk.Frame(parent)
        file_row.grid(row=row, column=1, sticky="w")
        ttk.Entry(file_row, textvariable=self.start_logo_path_var, width=20, state="readonly").pack(side="left")
        ttk.Button(file_row, text="Browse...", command=self._on_browse_logo).pack(side="left", padx=(6, 0))
        ttk.Button(file_row, text="Clear", command=self._on_clear_logo).pack(side="left", padx=(4, 0))
        return row + 1

    def _add_key_capture(self, parent, row, label, var):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=3)
        entry = ttk.Entry(parent, textvariable=var, width=12, state="readonly")
        entry.grid(row=row, column=1, sticky="w")

        def on_key(event):
            var.set(event.keysym.lower())
            return "break"

        entry.bind("<Key>", on_key)
        entry.bind("<Button-1>", lambda e: entry.focus_set())
        return row + 1

    # ---------- Camera preview ----------

    def _open_camera(self, index):
        if self.camera is not None:
            self.camera.release()
            self.camera = None
        try:
            self.camera = Camera(index)
            self.camera_status_var.set(f"Camera {index}: connected")
        except CameraError:
            self.camera = None
            self.camera_status_var.set(f"Camera {index}: not available")

    def _on_refresh_camera(self):
        self._open_camera(self.camera_index_var.get())

    def _on_browse_logo(self):
        path = filedialog.askopenfilename(
            title="Choose a start page logo",
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.gif *.bmp"), ("All files", "*.*")],
        )
        if path:
            self.start_logo_path_var.set(path)

    def _on_clear_logo(self):
        self.start_logo_path_var.set("")

    def _photos_dir_path(self) -> Path:
        photos_dir = Path(self.initial_config.get("photos_dir", "photos"))
        if not photos_dir.is_absolute():
            photos_dir = ROOT_DIR / photos_dir
        return photos_dir

    def _on_open_photos_folder(self):
        path = self._photos_dir_path()
        path.mkdir(parents=True, exist_ok=True)
        os.startfile(str(path))

    # ---------- Test credentials ----------

    def _sync_test_buttons(self):
        discord_ready = bool(self.discord_webhook_var.get().strip())
        telegram_ready = bool(self.telegram_token_var.get().strip() and self.telegram_chat_id_var.get().strip())
        ready = {"discord": discord_ready, "telegram": telegram_ready}
        for destination, button in self._test_buttons.items():
            in_flight = destination in self._tests_in_flight
            button.configure(state="disabled" if in_flight or not ready[destination] else "normal")

    def _run_test(self, destination, work):
        """work is a zero-arg callable returning an uploader.UploadResult, run on a background thread."""
        self._tests_in_flight.add(destination)
        self._set_test_status(destination, "Sending test message...", STATUS_COLOR_IDLE)
        self._sync_test_buttons()
        threading.Thread(target=lambda: self._test_queue.put(work()), daemon=True).start()

    def _on_test_discord(self):
        url = self.discord_webhook_var.get().strip()
        self._run_test("discord", lambda: uploader.test_discord(url))

    def _on_test_telegram(self):
        token = self.telegram_token_var.get().strip()
        chat_id = self.telegram_chat_id_var.get().strip()
        self._run_test("telegram", lambda: uploader.test_telegram(token, chat_id))

    def _set_test_status(self, destination, text, color):
        var = self._test_status_vars.get(destination)
        if var is None:
            return
        if len(text) > 120:
            text = text[:117] + "..."
        var.set(text)
        self._test_status_labels[destination].configure(foreground=color)

    def _poll_test_results(self):
        while True:
            try:
                result = self._test_queue.get_nowait()
            except queue.Empty:
                break
            self._tests_in_flight.discard(result.destination)
            color = STATUS_COLOR_SUCCESS if result.success else STATUS_COLOR_FAILURE
            self._set_test_status(result.destination, result.message, color)
            self._sync_test_buttons()
        self.root.after(TEST_POLL_INTERVAL_MS, self._poll_test_results)

    # ---------- Logs tab ----------

    def _on_open_log_folder(self):
        capture_log.LOG_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(str(capture_log.LOG_DIR))

    def _on_delete_log_entry(self):
        selection = self.log_tree.selection()
        if not selection:
            messagebox.showinfo("Delete Photo", "Select a photo in the table first.")
            return

        data = self._log_row_data.get(selection[0])
        if data is None:
            return
        if data["pending"]:
            messagebox.showinfo("Delete Photo", "This photo is still being sent - wait for it to finish, then try again.")
            return

        photo_file = data["photo_file"]
        if not photo_file:
            messagebox.showinfo("Delete Photo", "This entry has no photo file to delete.")
            return

        if not messagebox.askyesno("Delete Photo", f"Permanently delete {photo_file} and remove it from the log?"):
            return

        photo_path = self._photos_dir_path() / photo_file
        try:
            photo_path.unlink(missing_ok=True)
        except OSError as exc:
            messagebox.showerror("Delete Photo", f"Could not delete the photo file:\n{exc}")
            return

        capture_log.delete_entry(photo_file)
        self._refresh_logs()

    def _refresh_logs(self):
        entries = capture_log.read_entries()
        hourly, totals = capture_log.summarize(entries)
        self.log_summary_var.set(self._format_log_summary(totals))
        self._draw_log_chart(hourly)

        pending = capture_log.list_pending()
        self._draw_log_detail(entries, pending)
        # Keeps "time still listening" and attempt counts moving without a manual click - but only
        # while something is actually in flight, so an idle booth doesn't re-read the CSV forever.
        if pending:
            self.root.after(LOG_DETAIL_REFRESH_MS, self._refresh_logs)

    def _format_log_summary(self, totals):
        if totals["total"] == 0:
            return "No captures logged yet - photos taken in the booth will appear here."

        date_format = "%Y-%m-%d %H:%M"
        first = totals["first"].strftime(date_format) if totals["first"] else "?"
        last = totals["last"].strftime(date_format) if totals["last"] else "?"
        lines = [f"{totals['total']} photos logged  ·  {first} to {last}"]
        lines.append(f"Saved locally: {totals['saved_locally']} of {totals['total']}")

        destination_bits = []
        if totals["discord_attempts"]:
            destination_bits.append(
                f"Discord: {totals['discord_ok']} sent, {totals['discord_failed']} failed of {totals['discord_attempts']}"
            )
        if totals["telegram_attempts"]:
            destination_bits.append(
                f"Telegram: {totals['telegram_ok']} sent, {totals['telegram_failed']} failed of {totals['telegram_attempts']}"
            )
        if destination_bits:
            lines.append("   ·   ".join(destination_bits))
        return "\n".join(lines)

    def _draw_log_chart(self, hourly):
        canvas = self.log_canvas
        canvas.delete("all")

        x0 = CHART_PAD["left"]
        y0 = CHART_PAD["top"]
        x1 = CHART_WIDTH - CHART_PAD["right"]
        y1 = CHART_HEIGHT - CHART_PAD["bottom"]
        plot_h = y1 - y0

        max_count = max(hour["total"] for hour in hourly)
        if max_count == 0:
            canvas.create_line(x0, y1, x1, y1, fill="#888888")
            canvas.create_line(x0, y0, x0, y1, fill="#888888")
            canvas.create_text(
                (x0 + x1) / 2, (y0 + y1) / 2, text="No photos logged yet",
                fill="#888888", font=("Segoe UI", 10),
            )
            return

        step = next((s for s in CHART_Y_TICK_STEPS if s * 4 >= max_count), math.ceil(max_count / 4))
        y_max = step * 4

        for i in range(5):
            value = step * i
            y = y1 - round(value / y_max * plot_h)
            canvas.create_line(x0, y, x1, y, fill="#EAEAEA")
            canvas.create_text(x0 - 6, y, text=str(value), anchor="e", font=("Segoe UI", 7), fill="#555555")

        slot_w = (x1 - x0) / 24
        bar_w = max(6, slot_w * 0.62)

        for hour, data in enumerate(hourly):
            if data["total"] == 0:
                continue
            center = x0 + slot_w * (hour + 0.5)
            left = center - bar_w / 2
            cumulative = 0
            for key, color, _label in CHART_SEGMENTS:
                count = data[key]
                if not count:
                    continue
                bottom = y1 - round(cumulative / y_max * plot_h)
                top = y1 - round((cumulative + count) / y_max * plot_h)
                if bottom - top < 2:
                    top = bottom - 2
                canvas.create_rectangle(left, top, left + bar_w, bottom, fill=color, outline="")
                cumulative += count

        canvas.create_line(x0, y1, x1, y1, fill="#888888")
        canvas.create_line(x0, y0, x0, y1, fill="#888888")

        for hour in range(0, 24, 2):
            canvas.create_text(
                x0 + slot_w * (hour + 0.5), y1 + 4, text=f"{hour:02d}",
                anchor="n", font=("Segoe UI", 7), fill="#555555",
            )
        canvas.create_text(x1, y1 + 16, text="Hour of day", anchor="e", font=("Segoe UI", 7), fill="#888888")

    def _draw_log_detail(self, entries, pending):
        tree = self.log_tree
        tree.delete(*tree.get_children())
        self._log_row_data = {}

        for entry in pending:
            iid = tree.insert("", "end", values=self._pending_row_values(entry), tags=("pending",))
            self._log_row_data[iid] = {"photo_file": entry["photo_file"], "pending": True}

        recent = sorted(entries, key=lambda entry: entry["timestamp"], reverse=True)[:LOG_DETAIL_LIMIT]
        for entry in recent:
            iid = tree.insert(
                "", "end", values=self._resolved_row_values(entry), tags=(capture_log.classify_entry(entry),)
            )
            self._log_row_data[iid] = {"photo_file": entry["photo_file"], "pending": False}

    def _resolved_row_values(self, entry):
        return (
            entry["timestamp"].strftime("%m/%d %H:%M:%S"),
            entry["photo_file"] or "(no photo)",
            "✓" if entry["saved_locally"] else "✗",
            self._destination_cell(
                entry["discord_enabled"], entry["discord_success"], entry["discord_attempts"], entry["discord_message"]
            ),
            self._destination_cell(
                entry["telegram_enabled"], entry["telegram_success"], entry["telegram_attempts"], entry["telegram_message"]
            ),
            f"Resolved {entry['resolved_at'].strftime('%H:%M:%S')}",
        )

    def _pending_row_values(self, entry):
        remaining = (entry["deadline_at"] - datetime.now()).total_seconds()
        return (
            entry["captured_at"].strftime("%m/%d %H:%M:%S"),
            entry["photo_file"] or "(no photo)",
            "✓" if entry["saved_locally"] else "✗",
            self._destination_cell(
                entry["discord_enabled"], entry["discord_success"], entry["discord_attempts"], entry["discord_message"]
            ),
            self._destination_cell(
                entry["telegram_enabled"], entry["telegram_success"], entry["telegram_attempts"], entry["telegram_message"]
            ),
            f"Listening... {self._format_remaining(remaining)} left",
        )

    @staticmethod
    def _destination_cell(enabled, success, attempts, message):
        if not enabled:
            return "-"
        if attempts == 0:
            return "queued"
        if success:
            return f"sent ({attempts} tries)" if attempts > 1 else "sent"
        # Messages come back as "Discord: HTTP 502 ..." / "Telegram: could not read ..." - the
        # column already says which destination this is, so drop the redundant label prefix.
        detail = message.split(": ", 1)[-1] if message else ""
        if len(detail) > 40:
            detail = detail[:37] + "..."
        return f"failed x{attempts}: {detail}" if detail else f"failed x{attempts}"

    @staticmethod
    def _format_remaining(seconds):
        seconds = max(0, int(seconds))
        minutes, secs = divmod(seconds, 60)
        return f"{minutes}:{secs:02d}"

    def _update_preview(self):
        frame = self.camera.read_frame_rgb() if self.camera is not None else None
        if frame is not None:
            image = Image.fromarray(frame)
            image.thumbnail(PREVIEW_SIZE, Image.LANCZOS)
            canvas = Image.new("RGB", PREVIEW_SIZE, (20, 20, 20))
            offset = ((PREVIEW_SIZE[0] - image.width) // 2, (PREVIEW_SIZE[1] - image.height) // 2)
            canvas.paste(image, offset)
            photo = ImageTk.PhotoImage(canvas)
            self.preview_label.configure(image=photo)
            self.preview_label.image = photo  # keep a reference so it isn't garbage-collected

        self.root.after(PREVIEW_INTERVAL_MS, self._update_preview)

    # ---------- Actions ----------

    def _on_start(self):
        if self.camera is None:
            proceed = messagebox.askyesno(
                "No camera detected",
                f"Camera index {self.camera_index_var.get()} isn't available. Start anyway?",
            )
            if not proceed:
                return

        self.result = {
            **self.initial_config,
            "camera_index": self.camera_index_var.get(),
            "countdown_seconds": self.countdown_var.get(),
            "photo_review_seconds": self.photo_review_var.get(),
            "fullscreen": self.fullscreen_var.get(),
            "start_message": self.start_message_var.get().strip(),
            "start_logo_path": self.start_logo_path_var.get().strip(),
            "prompt_message": self.prompt_message_var.get().strip(),
            "review_message_top": self.review_message_top_var.get().strip(),
            "review_message_bottom": self.review_message_bottom_var.get().strip(),
            "scale_review_photo": self.scale_review_photo_var.get(),
            "capture_key": self.capture_key_var.get(),
            "quit_key": self.quit_key_var.get(),
            "discord_upload_enabled": self.discord_upload_enabled_var.get(),
            "discord_webhook_url": self.discord_webhook_var.get().strip(),
            "telegram_upload_enabled": self.telegram_upload_enabled_var.get(),
            "telegram_bot_token": self.telegram_token_var.get().strip(),
            "telegram_chat_id": self.telegram_chat_id_var.get().strip(),
            "telegram_max_retries": self.telegram_max_retries_var.get(),
            "monitor_enabled": self.monitor_enabled_var.get(),
            "monitor_port": self.monitor_port_var.get(),
            "monitor_show_url": self.monitor_show_url_var.get(),
        }
        self.remember_settings = self.remember_settings_var.get()
        self._cleanup()
        self.root.destroy()

    def _on_quit(self):
        self.result = None
        self._cleanup()
        self.root.destroy()

    def _cleanup(self):
        if self.camera is not None:
            self.camera.release()
            self.camera = None

    def run(self):
        self.root.mainloop()
        return self.result
