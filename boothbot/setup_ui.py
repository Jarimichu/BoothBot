"""A Tkinter setup screen (with a live webcam preview) shown before the fullscreen booth view."""
import tkinter as tk
from tkinter import messagebox, ttk

from PIL import Image, ImageTk

from . import __version__
from .camera import Camera, CameraError

PREVIEW_SIZE = (480, 360)
PREVIEW_INTERVAL_MS = 33


class SetupWindow:
    def __init__(self, config_data: dict):
        self.initial_config = config_data
        self.result = None
        self.camera = None

        self.root = tk.Tk()
        self.root.title(f"BoothBot Setup v{__version__}")
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self._on_quit)

        self.camera_index_var = tk.IntVar(value=config_data.get("camera_index", 0))
        self.camera_status_var = tk.StringVar(value="")
        self.countdown_var = tk.IntVar(value=config_data.get("countdown_seconds", 5))
        self.photo_review_var = tk.IntVar(value=config_data.get("photo_review_seconds", 5))
        self.post_capture_var = tk.IntVar(value=config_data.get("post_capture_display_seconds", 4))
        self.fullscreen_var = tk.BooleanVar(value=config_data.get("fullscreen", True))
        self.prompt_message_var = tk.StringVar(value=config_data.get("prompt_message", "Press the button to take a photo!"))
        self.review_message_top_var = tk.StringVar(
            value=config_data.get("review_message_top", "Thanks for coming to the con!")
        )
        self.review_message_bottom_var = tk.StringVar(
            value=config_data.get("review_message_bottom", "Please see your photo on the Telegram channel")
        )
        self.capture_key_var = tk.StringVar(value=config_data.get("capture_key", "space"))
        self.quit_key_var = tk.StringVar(value=config_data.get("quit_key", "escape"))
        self.discord_webhook_var = tk.StringVar(value=config_data.get("discord_webhook_url", ""))
        self.telegram_token_var = tk.StringVar(value=config_data.get("telegram_bot_token", ""))
        self.telegram_chat_id_var = tk.StringVar(value=config_data.get("telegram_chat_id", ""))

        self._build_ui()
        self._open_camera(self.camera_index_var.get())
        self._update_preview()

    # ---------- UI construction ----------

    def _build_ui(self):
        outer = ttk.Frame(self.root, padding=16)
        outer.grid(row=0, column=0, sticky="nsew")

        left = ttk.Frame(outer)
        left.grid(row=0, column=0, sticky="n", padx=(0, 24))
        right = ttk.Frame(outer)
        right.grid(row=0, column=1, sticky="n")

        # --- Left: camera preview ---
        ttk.Label(left, text="Camera Preview", font=("Segoe UI", 12, "bold")).grid(row=0, column=0, sticky="w")

        self.preview_label = ttk.Label(left, background="black")
        self.preview_label.grid(row=1, column=0, pady=(4, 4))
        self.preview_label.configure(width=PREVIEW_SIZE[0])

        camera_row = ttk.Frame(left)
        camera_row.grid(row=2, column=0, sticky="ew")
        ttk.Label(camera_row, text="Camera index:").pack(side="left")
        camera_spin = ttk.Spinbox(camera_row, from_=0, to=9, width=4, textvariable=self.camera_index_var)
        camera_spin.pack(side="left", padx=(6, 6))
        ttk.Button(camera_row, text="Refresh", command=self._on_refresh_camera).pack(side="left")

        ttk.Label(left, textvariable=self.camera_status_var, foreground="#555").grid(
            row=3, column=0, sticky="w", pady=(4, 0)
        )

        # --- Right: settings form ---
        row = 0
        ttk.Label(right, text="Booth Settings", font=("Segoe UI", 12, "bold")).grid(
            row=row, column=0, columnspan=2, sticky="w"
        )
        row += 1

        row = self._add_spinbox(right, row, "Countdown (seconds):", self.countdown_var, 1, 30)
        row = self._add_spinbox(right, row, "Photo review (seconds):", self.photo_review_var, 1, 60)
        row = self._add_entry(right, row, "Review message (top):", self.review_message_top_var, width=36)
        row = self._add_entry(right, row, "Review message (bottom):", self.review_message_bottom_var, width=36)
        row = self._add_spinbox(right, row, "Result display (seconds):", self.post_capture_var, 1, 30)
        row = self._add_entry(right, row, "Live view message:", self.prompt_message_var, width=36)
        row = self._add_key_capture(right, row, "Capture button key:", self.capture_key_var)
        row = self._add_key_capture(right, row, "Quit key:", self.quit_key_var)

        ttk.Checkbutton(right, text="Fullscreen", variable=self.fullscreen_var).grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(4, 8)
        )
        row += 1

        ttk.Separator(right, orient="horizontal").grid(row=row, column=0, columnspan=2, sticky="ew", pady=8)
        row += 1

        ttk.Label(right, text="Discord & Telegram", font=("Segoe UI", 12, "bold")).grid(
            row=row, column=0, columnspan=2, sticky="w"
        )
        row += 1

        row = self._add_entry(right, row, "Discord webhook URL:", self.discord_webhook_var, width=36)
        row = self._add_entry(right, row, "Telegram bot token:", self.telegram_token_var, width=36)
        row = self._add_entry(right, row, "Telegram chat ID:", self.telegram_chat_id_var, width=36)

        button_row = ttk.Frame(outer)
        button_row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(16, 0))
        ttk.Label(button_row, text=f"v{__version__}", foreground="#888").pack(side="left")
        ttk.Button(button_row, text="Quit", command=self._on_quit).pack(side="right", padx=(8, 0))
        ttk.Button(button_row, text="Start Photobooth", command=self._on_start).pack(side="right")

    def _add_spinbox(self, parent, row, label, var, from_, to):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=3)
        ttk.Spinbox(parent, from_=from_, to=to, width=6, textvariable=var).grid(row=row, column=1, sticky="w")
        return row + 1

    def _add_entry(self, parent, row, label, var, width=24):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=3)
        ttk.Entry(parent, textvariable=var, width=width).grid(row=row, column=1, sticky="w")
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
            "post_capture_display_seconds": self.post_capture_var.get(),
            "fullscreen": self.fullscreen_var.get(),
            "prompt_message": self.prompt_message_var.get().strip(),
            "review_message_top": self.review_message_top_var.get().strip(),
            "review_message_bottom": self.review_message_bottom_var.get().strip(),
            "capture_key": self.capture_key_var.get(),
            "quit_key": self.quit_key_var.get(),
            "discord_webhook_url": self.discord_webhook_var.get().strip(),
            "telegram_bot_token": self.telegram_token_var.get().strip(),
            "telegram_chat_id": self.telegram_chat_id_var.get().strip(),
        }
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
