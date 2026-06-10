import colorsys
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox, ttk

import serial


CONFIG_FILE = Path(__file__).with_name("turnup_config.json")
PORT = "/dev/ttyACM0"
BAUD = 115200
VOLUME_STEP = 2
BUTTON_DEBOUNCE_SECONDS = 0.2
LED_REFRESH_SECONDS = 0.1
INITIALIZATION_TIMEOUT_SECONDS = 2.5
INITIALIZATION_WATCHDOG_MS = 6000
CONTROLLER_PREVIEW_HEIGHT = 150
MIN_UI_SCALE = 0.9
MAX_UI_SCALE = 1.2
BASE_UI_WIDTH = 980
BASE_UI_HEIGHT = 700
BASE_LISTBOX_HEIGHT = 10
BASE_LISTBOX_FONT_SIZE = 11

KNOBS = [f"channel_{index}" for index in range(5)]
DEFAULT_LED_COLOR = "#FFFFFF"
BUTTON_ACTIONS = {"No action": "none", "Mute": "mute"}
DEFAULT_BUTTON_ACTION = "mute"
APP_TARGETS = {
    "Discord Voice": "WEBRTC VoiceEngine",
    "Firefox": "Firefox",
    "Helldivers 2": "Helldivers 2",
    "Line In / Capture": "70",
    "Master Volume": "@DEFAULT_AUDIO_SINK@",
    "Microphone": "@DEFAULT_AUDIO_SOURCE@",
    "Spotify": "Spotify",
    "Steam": "Steam",
}


def autostart_path(config_home=None):
    base = Path(config_home) if config_home else Path(
        os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
    )
    return base / "autostart" / "turnup-linux.desktop"


def desktop_exec_argument(value):
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def build_autostart_entry(python_executable=None, script_path=None):
    python_executable = Path(python_executable or sys.executable).resolve()
    script_path = Path(script_path or __file__).resolve()
    command = f"{desktop_exec_argument(python_executable)} {desktop_exec_argument(script_path)}"
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Turn Up\n"
        "Comment=Start the Turn Up Linux audio controller\n"
        f"Exec={command}\n"
        "Terminal=false\n"
        "X-GNOME-Autostart-enabled=true\n"
    )


def is_autostart_enabled(path=None):
    return Path(path or autostart_path()).is_file()


def set_autostart_enabled(enabled, path=None):
    target = Path(path or autostart_path())
    if enabled:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".tmp")
        temporary.write_text(build_autostart_entry(), encoding="utf-8")
        temporary.replace(target)
    else:
        target.unlink(missing_ok=True)


def default_config():
    return {
        **{knob: [] for knob in KNOBS},
        "_program_names": {},
        "_led_colors": {knob: DEFAULT_LED_COLOR for knob in KNOBS},
        "_button_actions": {knob: DEFAULT_BUTTON_ACTION for knob in KNOBS},
    }


def normalize_color(value):
    if not isinstance(value, str) or re.fullmatch(r"#[0-9a-fA-F]{6}", value) is None:
        return DEFAULT_LED_COLOR
    return value.upper()


def color_to_rgb(value):
    color = normalize_color(value)
    return tuple(int(color[index : index + 2], 16) for index in (1, 3, 5))


def rgb_to_hex(red, green, blue):
    return f"#{red:02X}{green:02X}{blue:02X}"


def normalize_button_action(value):
    return value if value in BUTTON_ACTIONS.values() else DEFAULT_BUTTON_ACTION


def load_config():
    config = default_config()
    try:
        with CONFIG_FILE.open(encoding="utf-8") as config_file:
            saved = json.load(config_file)
    except (OSError, json.JSONDecodeError):
        return config

    for knob in KNOBS:
        values = saved.get(knob, [])
        if isinstance(values, list):
            config[knob] = [value for value in values if value in APP_TARGETS]

    names = saved.get("_program_names", {})
    if isinstance(names, dict):
        config["_program_names"] = {
            key: value.strip()
            for key, value in names.items()
            if key in APP_TARGETS and isinstance(value, str) and value.strip()
        }

    colors = saved.get("_led_colors", {})
    if isinstance(colors, dict):
        config["_led_colors"] = {
            knob: normalize_color(colors.get(knob, DEFAULT_LED_COLOR))
            for knob in KNOBS
        }

    actions = saved.get("_button_actions", {})
    if isinstance(actions, dict):
        config["_button_actions"] = {
            knob: normalize_button_action(actions.get(knob, DEFAULT_BUTTON_ACTION))
            for knob in KNOBS
        }
    return config


def write_config(config):
    temporary_file = CONFIG_FILE.with_suffix(".tmp")
    with temporary_file.open("w", encoding="utf-8") as config_file:
        json.dump(config, config_file, indent=4)
        config_file.write("\n")
    temporary_file.replace(CONFIG_FILE)


def parse_packets(buffer):
    events = []
    position = 0
    header = b"\xff\xfe"

    while position <= len(buffer) - 3:
        if buffer[position : position + 2] != header:
            position += 1
            continue

        packet_type = buffer[position + 2]
        packet_length = {0x02: 3, 0x03: 6, 0x07: 4}.get(packet_type)
        if packet_length is None:
            position += 2
            continue
        if len(buffer) - position < packet_length:
            break

        if packet_type == 0x03:
            channel = buffer[position + 3]
            value = (buffer[position + 4] << 8) | buffer[position + 5]
            events.append(("knob", channel, value))
        elif packet_type == 0x07:
            events.append(("button", buffer[position + 3], None))
        position += packet_length

    return events, buffer[position:]


def get_audio_status():
    try:
        result = subprocess.run(
            ["wpctl", "status"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout


def get_stream_ids(targets, status):
    resolved = {target: [] for target in targets}
    searchable = {}

    for target in targets:
        real_target = APP_TARGETS.get(target, target)
        if real_target.startswith("@DEFAULT_AUDIO_") or real_target.isdigit():
            resolved[target] = [real_target]
        else:
            searchable[target] = real_target.lower()

    in_audio_streams = False
    for line in status.splitlines():
        stripped = line.strip()
        if "Streams:" in stripped:
            in_audio_streams = True
            continue
        if in_audio_streams and stripped.startswith(("Video", "Settings")):
            break
        if not in_audio_streams:
            continue

        id_match = re.match(r"^[^0-9]*(\d+)\.\s", stripped)
        if id_match is None:
            continue
        stream_id = id_match.group(1)
        lowered = stripped.lower()
        for target, search_name in searchable.items():
            if search_name in lowered:
                resolved[target].append(stream_id)

    return resolved


def set_volume(target, percent):
    try:
        subprocess.run(
            ["wpctl", "set-volume", target, f"{percent}%"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        pass


def set_muted(target, muted):
    try:
        result = subprocess.run(
            ["wpctl", "set-mute", target, "1" if muted else "0"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return False, str(error)
    return result.returncode == 0, result.stderr.strip()


def build_light_message(channel_colors):
    message = bytearray(48)
    message[0] = 0xFE
    message[1] = 0x05
    message[-1] = 0xFF

    for channel, color in enumerate(channel_colors):
        red, green, blue = color
        start = 2 + channel * 9
        message[start : start + 9] = bytes((red, green, blue)) * 3

    return bytes(message)


def set_channel_leds(controller, channel_colors):
    controller.write(build_light_message(channel_colors))
    controller.flush()


class ColorWheelDialog:
    SIZE = 280

    def __init__(self, parent, title, initial_color, on_preview):
        self.on_preview = on_preview
        self.result = None
        red, green, blue = color_to_rgb(initial_color)
        self.hue, self.saturation, self.value = colorsys.rgb_to_hsv(
            red / 255,
            green / 255,
            blue / 255,
        )

        self.window = tk.Toplevel(parent)
        self.window.title(title)
        self.window.configure(bg="#111827")
        self.window.resizable(False, False)
        self.window.transient(parent)
        self.window.grab_set()
        self.window.protocol("WM_DELETE_WINDOW", self.cancel)

        content = tk.Frame(self.window, bg="#111827", padx=18, pady=18)
        content.pack()
        self.canvas = tk.Canvas(
            content,
            width=self.SIZE,
            height=self.SIZE,
            bg="#111827",
            highlightthickness=0,
            cursor="crosshair",
        )
        self.canvas.pack()
        self.wheel_image = self._make_wheel_image()
        self.canvas.create_image(0, 0, anchor="nw", image=self.wheel_image)
        self.indicator = self.canvas.create_oval(0, 0, 0, 0, outline="white", width=3)
        self.canvas.bind("<Button-1>", self.pick_from_wheel)
        self.canvas.bind("<B1-Motion>", self.pick_from_wheel)

        tk.Label(
            content,
            text="Brightness",
            bg="#111827",
            fg="#d1d5db",
            anchor="w",
        ).pack(fill="x", pady=(14, 0))
        self.brightness = tk.Scale(
            content,
            from_=100,
            to=0,
            orient="horizontal",
            showvalue=False,
            command=self.change_brightness,
            bg="#111827",
            fg="#d1d5db",
            troughcolor="#374151",
            activebackground="#60a5fa",
            highlightthickness=0,
            length=self.SIZE,
        )
        self.brightness.pack()

        preview_row = tk.Frame(content, bg="#111827")
        preview_row.pack(fill="x", pady=(12, 14))
        self.preview = tk.Label(preview_row, width=4, relief="flat")
        self.preview.pack(side="left")
        self.hex_var = tk.StringVar()
        tk.Label(
            preview_row,
            textvariable=self.hex_var,
            bg="#111827",
            fg="#f9fafb",
            font=("TkDefaultFont", 12, "bold"),
        ).pack(side="left", padx=10)

        buttons = tk.Frame(content, bg="#111827")
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Cancel", command=self.cancel).pack(side="right")
        ttk.Button(buttons, text="Apply", command=self.apply, style="Accent.TButton").pack(
            side="right", padx=(0, 8)
        )

        self.brightness.set(round(self.value * 100))
        self._update_indicator()
        self._preview_color()
        self.window.update_idletasks()
        self.window.geometry(
            f"+{parent.winfo_rootx() + 80}+{parent.winfo_rooty() + 60}"
        )
        parent.wait_window(self.window)

    def _make_wheel_image(self):
        pixels = bytearray()
        center = (self.SIZE - 1) / 2
        radius = center - 3
        for y in range(self.SIZE):
            for x in range(self.SIZE):
                dx = x - center
                dy = y - center
                saturation = math.hypot(dx, dy) / radius
                if saturation <= 1:
                    hue = (math.atan2(dy, dx) / (2 * math.pi)) % 1
                    red, green, blue = colorsys.hsv_to_rgb(hue, saturation, 1)
                    pixels.extend((round(red * 255), round(green * 255), round(blue * 255)))
                else:
                    pixels.extend((17, 24, 39))
        ppm = f"P6\n{self.SIZE} {self.SIZE}\n255\n".encode("ascii") + pixels
        return tk.PhotoImage(data=ppm, format="PPM")

    def pick_from_wheel(self, event):
        center = (self.SIZE - 1) / 2
        dx = event.x - center
        dy = event.y - center
        radius = center - 3
        distance = math.hypot(dx, dy)
        if distance > radius:
            dx *= radius / distance
            dy *= radius / distance
            distance = radius
        self.hue = (math.atan2(dy, dx) / (2 * math.pi)) % 1
        self.saturation = distance / radius
        self._update_indicator()
        self._preview_color()

    def change_brightness(self, value):
        self.value = int(value) / 100
        self._preview_color()

    def _selected_color(self):
        red, green, blue = colorsys.hsv_to_rgb(self.hue, self.saturation, self.value)
        return rgb_to_hex(round(red * 255), round(green * 255), round(blue * 255))

    def _update_indicator(self):
        center = (self.SIZE - 1) / 2
        radius = (center - 3) * self.saturation
        angle = self.hue * 2 * math.pi
        x = center + math.cos(angle) * radius
        y = center + math.sin(angle) * radius
        self.canvas.coords(self.indicator, x - 6, y - 6, x + 6, y + 6)

    def _preview_color(self):
        color = self._selected_color()
        self.hex_var.set(color)
        self.preview.configure(bg=color)
        self.on_preview(color)

    def apply(self):
        self.result = self._selected_color()
        self.window.destroy()

    def cancel(self):
        self.window.destroy()


class TurnUpApp:
    def __init__(self, root):
        self.root = root
        self.config = load_config()
        self.config_lock = threading.Lock()
        self.stop_event = threading.Event()
        self.controller_thread = None
        self.last_percent = {}
        self.last_button_press = {}
        self.channel_muted = {knob: False for knob in KNOBS}
        self.listboxes = {}
        self.color_buttons = {}
        self.button_action_vars = {}
        self.channel_cards = {}
        self.preview_items = {}
        self.active_listbox = None
        self.active_channel = None
        self.pending_channel = None
        self.controller_y = 0
        self.controller_animation = None
        self.controller_initialized = False
        self.initialization_watchdog = None
        self.ui_scale = 1.0
        self.controller_preview_height = CONTROLLER_PREVIEW_HEIGHT
        self.status_var = tk.StringVar(value="Starting controller...")
        self.autostart_var = tk.BooleanVar(value=is_autostart_enabled())
        self.ordered_apps = []

        self._configure_window()
        self._build_ui()
        self.refresh_apps(show_status=False)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(350, self.start_controller)

    def _configure_window(self):
        self.root.title("Turn Up - Linux Audio Controller")
        self.root.geometry(f"{BASE_UI_WIDTH}x{BASE_UI_HEIGHT}")
        self.root.minsize(820, 620)
        self.root.configure(bg="#111827")

        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure("App.TFrame", background="#111827")
        style.configure("Card.TFrame", background="#1f2937", relief="flat")
        style.configure(
            "Title.TLabel",
            background="#111827",
            foreground="#f9fafb",
            font=("TkDefaultFont", 22, "bold"),
        )
        style.configure(
            "Subtitle.TLabel",
            background="#111827",
            foreground="#9ca3af",
            font=("TkDefaultFont", 10),
        )
        style.configure(
            "Channel.TLabel",
            background="#1f2937",
            foreground="#f9fafb",
            font=("TkDefaultFont", 12, "bold"),
        )
        style.configure(
            "Hint.TLabel",
            background="#1f2937",
            foreground="#9ca3af",
            font=("TkDefaultFont", 9),
        )
        style.configure(
            "Status.TLabel",
            background="#111827",
            foreground="#d1d5db",
            font=("TkDefaultFont", 10),
        )
        style.configure(
            "Accent.TButton",
            background="#2563eb",
            foreground="#ffffff",
            padding=(16, 9),
            font=("TkDefaultFont", 10, "bold"),
        )
        style.map("Accent.TButton", background=[("active", "#1d4ed8")])
        style.configure("Secondary.TButton", padding=(10, 6))

    def _build_ui(self):
        outer = ttk.Frame(self.root, style="App.TFrame", padding=(18, 14))
        outer.pack(fill="both", expand=True)

        title_row = ttk.Frame(outer, style="App.TFrame")
        title_row.pack(fill="x")
        ttk.Label(title_row, text="Turn Up", style="Title.TLabel").pack(side="left")
        menu_button = ttk.Menubutton(title_row, text="Settings", style="Secondary.TButton")
        settings_menu = tk.Menu(menu_button, tearoff=False)
        settings_menu.add_command(label="Restart Controller", command=self.restart_controller)
        settings_menu.add_separator()
        settings_menu.add_checkbutton(
            label="Start with Linux",
            variable=self.autostart_var,
            command=self.toggle_autostart,
        )
        menu_button.configure(menu=settings_menu)
        menu_button.pack(side="right")
        ttk.Label(
            outer,
            text="Click a channel to configure its programs, LED color, and button action.",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(0, 6))

        self.content_stage = tk.Frame(outer, bg="#111827")
        self.content_stage.pack(fill="both", expand=True)
        self.content_stage.bind("<Configure>", self._layout_content_stage)
        self.root.bind("<Configure>", self._layout_content_stage, add="+")

        self._build_controller_preview(self.content_stage)

        self.initialization_var = tk.StringVar(value="Initializing controller...")
        self.initialization_label = tk.Label(
            self.content_stage,
            textvariable=self.initialization_var,
            bg="#1f2937",
            fg="#d1d5db",
            padx=14,
            pady=7,
            font=("TkDefaultFont", 10, "bold"),
            justify="center",
        )
        self.initialization_label.place(relx=0.5, rely=0.5, anchor="center")

        self.settings_host = ttk.Frame(self.content_stage, style="App.TFrame")
        self.settings_host.columnconfigure(0, weight=1)
        self.settings_host.rowconfigure(0, weight=1)

        for index, knob in enumerate(KNOBS):
            card = ttk.Frame(self.settings_host, style="Card.TFrame", padding=14)
            card.grid(row=0, column=0)
            card.grid_remove()
            self.channel_cards[knob] = card

            header = ttk.Frame(card, style="Card.TFrame")
            header.pack(fill="x")
            ttk.Label(header, text=f"Channel {index + 1} Settings", style="Channel.TLabel").pack(
                side="left"
            )
            ttk.Button(
                header,
                text="Close",
                command=self.hide_channel_settings,
                style="Secondary.TButton",
            ).pack(side="right")
            ttk.Label(
                card,
                text="Knob controls volume; set button action below",
                style="Hint.TLabel",
            ).pack(anchor="w", pady=(0, 8))

            settings_body = ttk.Frame(card, style="Card.TFrame")
            settings_body.pack(fill="both", expand=True)
            settings_body.columnconfigure(0, weight=4)
            settings_body.columnconfigure(1, weight=3)
            settings_body.rowconfigure(0, weight=1)

            list_frame = tk.Frame(settings_body, bg="#1f2937")
            list_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
            scrollbar = ttk.Scrollbar(list_frame, orient="vertical")
            listbox = tk.Listbox(
                list_frame,
                selectmode="multiple",
                exportselection=False,
                activestyle="none",
                bg="#111827",
                fg="#e5e7eb",
                selectbackground="#2563eb",
                selectforeground="#ffffff",
                highlightthickness=1,
                highlightbackground="#374151",
                highlightcolor="#60a5fa",
                borderwidth=0,
                height=BASE_LISTBOX_HEIGHT,
                font=("TkDefaultFont", BASE_LISTBOX_FONT_SIZE),
                yscrollcommand=scrollbar.set,
            )
            scrollbar.config(command=listbox.yview)
            listbox.pack(side="left", fill="both", expand=True)
            scrollbar.pack(side="right", fill="y")
            listbox.bind("<Button-1>", self.activate_listbox, add="+")
            listbox.bind(
                "<<ListboxSelect>>",
                lambda _event, selected_knob=knob: self.mapping_changed(selected_knob),
            )
            self.listboxes[knob] = listbox

            options = ttk.Frame(settings_body, style="Card.TFrame")
            options.grid(row=0, column=1, sticky="nsew")

            color = self.config["_led_colors"][knob]
            color_button = tk.Button(
                options,
                text="LED Color",
                command=lambda selected_knob=knob: self.choose_led_color(selected_knob),
                bg=color,
                fg=self._contrast_text_color(color),
                activebackground=color,
                activeforeground=self._contrast_text_color(color),
                relief="flat",
                borderwidth=0,
                padx=10,
                pady=6,
            )
            color_button.pack(fill="x")
            self.color_buttons[knob] = color_button

            ttk.Label(options, text="Button Action", style="Hint.TLabel").pack(
                anchor="w", pady=(10, 3)
            )
            action_name = next(
                name
                for name, value in BUTTON_ACTIONS.items()
                if value == self.config["_button_actions"][knob]
            )
            action_var = tk.StringVar(value=action_name)
            action_picker = ttk.Combobox(
                options,
                textvariable=action_var,
                values=tuple(BUTTON_ACTIONS),
                state="readonly",
            )
            action_picker.pack(fill="x")
            action_picker.bind(
                "<<ComboboxSelected>>",
                lambda _event, selected_knob=knob: self.change_button_action(selected_knob),
            )
            self.button_action_vars[knob] = action_var

        ttk.Label(outer, textvariable=self.status_var, style="Status.TLabel").pack(
            anchor="w", pady=(6, 0)
        )

    def show_channel_settings(self, knob):
        if not self.controller_initialized:
            return
        if self.active_channel == knob:
            return
        if self.active_channel is not None:
            self.channel_cards[self.active_channel].grid_remove()
            self.channel_cards[knob].grid()
            self.active_channel = knob
            self.active_listbox = self.listboxes[knob]
            self.update_controller_preview()
            return

        self.pending_channel = knob
        self.update_controller_preview()
        self._animate_controller(self._controller_top_y(), self._reveal_channel_settings)

    def _reveal_channel_settings(self):
        knob = self.pending_channel
        if knob is None:
            return
        self.pending_channel = None
        self.active_channel = knob
        self.active_listbox = self.listboxes[knob]
        self.channel_cards[knob].grid()
        self.channel_cards[knob].tkraise()
        self._place_settings_host()
        self.update_controller_preview()

    def hide_channel_settings(self):
        if self.active_channel is not None:
            self.channel_cards[self.active_channel].grid_remove()
        self.active_channel = None
        self.pending_channel = None
        self.active_listbox = None
        self.settings_host.place_forget()
        self.update_controller_preview()
        self._animate_controller(self._controller_center_y())

    def _controller_top_y(self):
        return 0

    def _controller_center_y(self):
        return max(0, (self.content_stage.winfo_height() - self.controller_preview_height) // 2)

    def _compute_ui_scale(self):
        width = max(1, self.content_stage.winfo_width())
        height = max(1, self.content_stage.winfo_height())
        scale = min(width / BASE_UI_WIDTH, height / BASE_UI_HEIGHT)
        return max(MIN_UI_SCALE, min(MAX_UI_SCALE, scale))

    def _apply_ui_scale(self, scale):
        if abs(scale - self.ui_scale) < 0.03:
            return

        self.ui_scale = scale
        self.controller_preview_height = round(CONTROLLER_PREVIEW_HEIGHT * scale)
        self.controller_canvas.configure(height=self.controller_preview_height)

        listbox_height = max(BASE_LISTBOX_HEIGHT, round(BASE_LISTBOX_HEIGHT * scale))
        listbox_font_size = max(BASE_LISTBOX_FONT_SIZE, round(BASE_LISTBOX_FONT_SIZE * scale))
        listbox_font = ("TkDefaultFont", listbox_font_size)
        button_padx = max(10, round(10 * scale))
        button_pady = max(6, round(6 * scale))

        for listbox in self.listboxes.values():
            listbox.configure(height=listbox_height, font=listbox_font)

        for button in self.color_buttons.values():
            button.configure(padx=button_padx, pady=button_pady)

        self._layout_content_stage()

    def _layout_content_stage(self, event=None):
        self._apply_ui_scale(self._compute_ui_scale())
        if not self.controller_initialized:
            self.preview_frame.place_forget()
            self.settings_host.place_forget()
            return
        if self.controller_animation is None:
            target = self._controller_top_y() if self.active_channel else self._controller_center_y()
            self.controller_y = target
            self.preview_frame.place(
                x=0, y=target, relwidth=1, height=self.controller_preview_height
            )
        if self.active_channel is not None:
            self._place_settings_host()

    def show_initialization(self, message):
        self.controller_initialized = False
        self.preview_frame.place_forget()
        self.settings_host.place_forget()
        self.initialization_var.set(message)
        self.initialization_label.place(relx=0.5, rely=0.5, anchor="center")
        self.initialization_label.lift()

    def finish_initialization(self):
        if self.controller_initialized:
            return
        self.controller_initialized = True
        if self.initialization_watchdog is not None:
            self.root.after_cancel(self.initialization_watchdog)
            self.initialization_watchdog = None
        self.initialization_label.place_forget()
        self.controller_y = self._controller_center_y()
        self.preview_frame.place(
            x=0, y=self.controller_y, relwidth=1, height=self.controller_preview_height
        )
        self.preview_frame.lift()
        self.update_controller_preview()
        self.status_var.set(f"Controller connected on {PORT}")

    def _place_settings_host(self):
        settings_y = self.controller_preview_height + round(20 * self.ui_scale)
        height = max(1, self.content_stage.winfo_height() - settings_y)
        self.settings_host.place(x=0, y=settings_y, relwidth=1, height=height)
        self.settings_host.lift()

    def _animate_controller(self, target_y, on_complete=None):
        if self.controller_animation is not None:
            self.root.after_cancel(self.controller_animation)
            self.controller_animation = None

        start_y = self.controller_y
        distance = target_y - start_y
        steps = 10

        def step(frame=1):
            progress = frame / steps
            eased = 1 - (1 - progress) ** 3
            self.controller_y = round(start_y + distance * eased)
            self.preview_frame.place(
                x=0, y=self.controller_y, relwidth=1, height=self.controller_preview_height
            )
            if frame < steps:
                self.controller_animation = self.root.after(16, step, frame + 1)
                return
            self.controller_animation = None
            self.controller_y = target_y
            if on_complete is not None:
                on_complete()

        step()

    def toggle_autostart(self):
        enabled = self.autostart_var.get()
        try:
            set_autostart_enabled(enabled)
        except OSError as error:
            self.autostart_var.set(is_autostart_enabled())
            messagebox.showerror("Startup setting failed", str(error), parent=self.root)
            self.status_var.set("Could not update startup setting")
            return
        state = "enabled" if enabled else "disabled"
        self.status_var.set(f"Start with Linux {state}")

    def mapping_changed(self, knob):
        self.active_listbox = self.listboxes[knob]
        self.save_config(status_message=f"Channel {KNOBS.index(knob) + 1} mapping saved")

    def _build_controller_preview(self, parent):
        self.preview_frame = tk.Frame(parent, bg="#111827")
        self.controller_canvas = tk.Canvas(
            self.preview_frame,
            height=self.controller_preview_height,
            bg="#111827",
            highlightthickness=0,
        )
        self.controller_canvas.pack(fill="x")
        self.controller_canvas.bind("<Configure>", self._draw_controller_preview)

    def _draw_controller_preview(self, event=None):
        canvas = self.controller_canvas
        width = max(canvas.winfo_width(), 760)
        canvas.delete("all")
        self.preview_items.clear()

        controller_width = min(round(760 * self.ui_scale), width - 30)
        left = (width - controller_width) / 2
        right = left + controller_width
        top = 10
        bottom = self.controller_preview_height - 10
        canvas.create_rectangle(
            left + 5,
            top + 7,
            right + 5,
            bottom + 7,
            fill="#070b12",
            outline="",
        )
        canvas.create_rectangle(
            left,
            top,
            right,
            bottom,
            fill="#151b26",
            outline="#374151",
            width=2,
        )
        canvas.create_text(
            left + 14,
            top + 10,
            text="TURN UP",
            anchor="nw",
            fill="#9ca3af",
            font=("TkDefaultFont", max(8, round(8 * self.ui_scale)), "bold"),
        )

        spacing = (right - left - 56) / len(KNOBS)
        for index, knob in enumerate(KNOBS):
            center_x = left + 28 + spacing * (index + 0.5)
            center_y = self.controller_preview_height * 0.58
            tag = f"preview_{knob}"
            canvas.create_oval(
                center_x - 34,
                center_y - 34,
                center_x + 34,
                center_y + 34,
                fill="#0b0f17",
                outline="#4b5563",
                width=2,
                tags=tag,
            )
            knob_face = canvas.create_oval(
                center_x - 25,
                center_y - 25,
                center_x + 25,
                center_y + 25,
                fill="#252d3a",
                outline="#6b7280",
                width=2,
                tags=tag,
            )
            indicator = canvas.create_line(
                center_x,
                center_y,
                center_x,
                center_y - 19,
                fill="#f9fafb",
                width=3,
                capstyle="round",
                tags=tag,
            )
            light_arc = canvas.create_arc(
                center_x - 38,
                center_y - 38,
                center_x + 38,
                center_y + 38,
                start=0,
                extent=180,
                style="arc",
                outline="#FFFFFF",
                width=9,
                tags=tag,
            )
            state = canvas.create_text(
                center_x,
                self.controller_preview_height - round(20 * self.ui_scale),
                text=f"CH {index + 1}  ACTIVE",
                fill="#9ca3af",
                font=("TkDefaultFont", max(8, round(8 * self.ui_scale)), "bold"),
                tags=tag,
            )
            canvas.tag_bind(
                tag,
                "<Button-1>",
                lambda _event, item=knob: self.show_channel_settings(item),
            )
            canvas.tag_bind(tag, "<Enter>", lambda _event: canvas.configure(cursor="hand2"))
            canvas.tag_bind(tag, "<Leave>", lambda _event: canvas.configure(cursor=""))
            self.preview_items[knob] = {
                "center": (center_x, center_y),
                "face": knob_face,
                "indicator": indicator,
                "light_arc": light_arc,
                "state": state,
            }

        self.update_controller_preview()

    def update_controller_preview(self, knob=None):
        knobs = [knob] if knob is not None else KNOBS
        for item in knobs:
            preview = self.preview_items.get(item)
            if preview is None:
                continue
            muted = self.channel_muted[item]
            color = "#080B10" if muted else self.config["_led_colors"][item]
            self.controller_canvas.itemconfigure(preview["light_arc"], outline=color)
            self.controller_canvas.itemconfigure(
                preview["face"],
                outline=(
                    "#60a5fa"
                    if self.active_channel == item or self.pending_channel == item
                    else "#ef4444"
                    if muted
                    else "#6b7280"
                ),
                width=(
                    3
                    if self.active_channel == item or self.pending_channel == item
                    else 2
                ),
            )
            self.controller_canvas.itemconfigure(
                preview["state"],
                text=f"CH {KNOBS.index(item) + 1}  {'MUTED' if muted else 'ACTIVE'}",
                fill=(
                    "#60a5fa"
                    if self.active_channel == item or self.pending_channel == item
                    else "#ef4444"
                    if muted
                    else "#9ca3af"
                ),
            )
            percent = self.last_percent.get(item, 50)
            angle = math.radians(225 - percent * 2.7)
            center_x, center_y = preview["center"]
            end_x = center_x + math.cos(angle) * 19
            end_y = center_y - math.sin(angle) * 19
            self.controller_canvas.coords(
                preview["indicator"],
                center_x,
                center_y,
                end_x,
                end_y,
            )

    def set_status(self, message):
        self.root.after(0, self.status_var.set, message)

    def display_name(self, app_name):
        return self.config["_program_names"].get(app_name, app_name)

    def refresh_apps(self, show_status=True):
        selected_by_knob = {
            knob: self._selected_apps(listbox) for knob, listbox in self.listboxes.items()
        }
        self.ordered_apps = sorted(APP_TARGETS, key=lambda app: self.display_name(app).lower())

        for knob, listbox in self.listboxes.items():
            selected = selected_by_knob[knob] or set(self.config.get(knob, []))
            listbox.delete(0, tk.END)
            for index, app_name in enumerate(self.ordered_apps):
                listbox.insert(tk.END, self.display_name(app_name))
                if app_name in selected:
                    listbox.selection_set(index)

        if show_status:
            self.status_var.set("Program list refreshed")

    def _selected_apps(self, listbox):
        return {
            self.ordered_apps[index]
            for index in listbox.curselection()
            if index < len(self.ordered_apps)
        }

    def activate_listbox(self, event):
        self.active_listbox = event.widget

    @staticmethod
    def _contrast_text_color(color):
        red, green, blue = color_to_rgb(color)
        return "#111827" if red * 299 + green * 587 + blue * 114 > 150000 else "#FFFFFF"

    def _set_led_color(self, knob, color):
        color = normalize_color(color)
        with self.config_lock:
            self.config["_led_colors"][knob] = color
        button = self.color_buttons[knob]
        text_color = self._contrast_text_color(color)
        button.configure(
            text=f"LED Color  {color}",
            bg=color,
            fg=text_color,
            activebackground=color,
            activeforeground=text_color,
        )
        self.update_controller_preview(knob)

    def choose_led_color(self, knob):
        current = self.config["_led_colors"][knob]
        dialog = ColorWheelDialog(
            self.root,
            f"Channel {KNOBS.index(knob) + 1} LED Color",
            current,
            lambda color: self._set_led_color(knob, color),
        )
        if dialog.result is None:
            self._set_led_color(knob, current)
            return

        selected = dialog.result
        self._set_led_color(knob, selected)
        self.save_config()
        self.status_var.set(f"Channel {KNOBS.index(knob) + 1} LED color set to {selected}")

    def change_button_action(self, knob):
        action_name = self.button_action_vars[knob].get()
        action = BUTTON_ACTIONS.get(action_name, DEFAULT_BUTTON_ACTION)
        with self.config_lock:
            self.config["_button_actions"][knob] = action
        self.save_config()
        self.status_var.set(
            f"Channel {KNOBS.index(knob) + 1} button action set to {action_name}"
        )

    def save_config(self, status_message="Settings saved"):
        for knob, listbox in self.listboxes.items():
            self.config[knob] = sorted(self._selected_apps(listbox), key=str.lower)

        try:
            write_config(self.config)
        except OSError as error:
            messagebox.showerror("Could not save", str(error), parent=self.root)
            self.status_var.set("Mapping could not be saved")
            return False

        with self.config_lock:
            self.config = json.loads(json.dumps(self.config))
        self.status_var.set(status_message)
        return True

    def config_snapshot(self):
        with self.config_lock:
            return {knob: list(self.config.get(knob, [])) for knob in KNOBS}

    def led_colors_snapshot(self):
        with self.config_lock:
            return [
                (0, 0, 0)
                if self.channel_muted[knob]
                else color_to_rgb(self.config["_led_colors"][knob])
                for knob in KNOBS
            ]

    def start_controller(self):
        if self.controller_thread and self.controller_thread.is_alive():
            return
        self.controller_initialized = False
        self.show_initialization("Initializing controller...")
        if self.initialization_watchdog is not None:
            self.root.after_cancel(self.initialization_watchdog)
        self.initialization_watchdog = self.root.after(
            INITIALIZATION_WATCHDOG_MS, self._force_finish_initialization
        )
        self.stop_event.clear()
        self.controller_thread = threading.Thread(target=self.control_loop, daemon=True)
        self.controller_thread.start()

    def _force_finish_initialization(self):
        self.initialization_watchdog = None
        if self.controller_initialized:
            return
        self.finish_initialization()

    def restart_controller(self):
        self.save_config()
        self.stop_event.set()
        self.status_var.set("Restarting controller...")
        self.root.after(200, self._finish_restart)

    def _finish_restart(self):
        if self.controller_thread and self.controller_thread.is_alive():
            self.root.after(100, self._finish_restart)
            return
        self.last_percent.clear()
        self.last_button_press.clear()
        self.start_controller()

    def control_loop(self):
        try:
            controller = serial.Serial(PORT, BAUD, timeout=0.1)
        except (OSError, serial.SerialException) as error:
            self.set_status(f"Serial connection failed: {error}")
            self.root.after(
                0,
                self.show_initialization,
                "Controller not connected\nOpen Settings and restart after reconnecting it",
            )
            return

        try:
            time.sleep(3)
            if self.stop_event.is_set():
                return
            controller.reset_input_buffer()
            set_channel_leds(controller, self.led_colors_snapshot())
            self.set_status("Syncing controller state...")
            buffer = b""
            synced_channels = set()
            syncing = True
            sync_started = time.monotonic()
            next_led_refresh = time.monotonic() + LED_REFRESH_SECONDS

            while not self.stop_event.is_set():
                now = time.monotonic()
                if now >= next_led_refresh:
                    set_channel_leds(controller, self.led_colors_snapshot())
                    next_led_refresh = now + LED_REFRESH_SECONDS

                buffer += controller.read(64)
                events, buffer = parse_packets(buffer)
                if len(buffer) > 128:
                    buffer = buffer[-5:]

                updates = {}
                for event_type, channel, value in events:
                    knob = f"channel_{channel}"
                    if knob not in KNOBS:
                        continue
                    if event_type == "button":
                        with self.config_lock:
                            button_action = self.config["_button_actions"][knob]
                        if button_action == "none":
                            continue
                        now = time.monotonic()
                        if now - self.last_button_press.get(knob, 0) >= BUTTON_DEBOUNCE_SECONDS:
                            self.last_button_press[knob] = now
                            muted = not self.channel_muted[knob]
                            success, message = self.apply_mute_update(knob, muted)
                            if success:
                                self.channel_muted[knob] = muted
                                set_channel_leds(controller, self.led_colors_snapshot())
                                self.root.after(0, self.update_controller_preview, knob)
                                state = "muted" if muted else "unmuted"
                                self.set_status(f"Channel {channel + 1} {state}")
                            else:
                                action = "mute" if muted else "unmute"
                                self.set_status(f"Channel {channel + 1} {action} failed: {message}")
                        continue

                    percent = max(0, min(100, round((value / 1023) * 100)))
                    if syncing:
                        self.last_percent[knob] = percent
                        synced_channels.add(channel)
                        self.root.after(0, self.update_controller_preview, knob)
                        if (
                            len(synced_channels) == len(KNOBS)
                            or (
                                synced_channels
                                and now - sync_started >= INITIALIZATION_TIMEOUT_SECONDS
                            )
                        ):
                            syncing = False
                            self.root.after(0, self.finish_initialization)
                        continue

                    previous = self.last_percent.get(knob)
                    if previous is None or abs(percent - previous) >= VOLUME_STEP:
                        updates[knob] = percent
                        self.last_percent[knob] = percent
                        self.root.after(0, self.update_controller_preview, knob)

                if updates:
                    self.apply_volume_updates(updates)
        except (OSError, serial.SerialException) as error:
            self.set_status(f"Controller error: {error}")
        finally:
            controller.close()
            if not self.stop_event.is_set():
                self.set_status("Controller disconnected")

    def apply_volume_updates(self, updates):
        config = self.config_snapshot()
        targets = {
            app_name
            for knob in updates
            for app_name in config.get(knob, [])
        }
        stream_ids = get_stream_ids(targets, get_audio_status())

        for knob, percent in updates.items():
            for app_name in config.get(knob, []):
                for stream_id in stream_ids.get(app_name, []):
                    set_volume(stream_id, percent)

    def apply_mute_update(self, knob, muted):
        config = self.config_snapshot()
        targets = config.get(knob, [])
        stream_ids = get_stream_ids(targets, get_audio_status())
        resolved_ids = [
            stream_id
            for app_name in targets
            for stream_id in stream_ids.get(app_name, [])
        ]

        if not targets:
            return False, "no programs are mapped"
        if not resolved_ids:
            return False, "mapped programs are not currently running"

        errors = []
        for stream_id in resolved_ids:
            success, error = set_muted(stream_id, muted)
            if not success:
                errors.append(error or f"wpctl rejected target {stream_id}")

        if errors:
            return False, errors[0]
        return True, ""

    def close(self):
        self.save_config()
        self.stop_event.set()
        if self.initialization_watchdog is not None:
            self.root.after_cancel(self.initialization_watchdog)
            self.initialization_watchdog = None
        self.root.destroy()


def main():
    root = tk.Tk()
    TurnUpApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
