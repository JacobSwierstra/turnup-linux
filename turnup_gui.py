import colorsys
import configparser
import json
import math
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox, ttk

import serial


CONFIG_DIR = Path.home() / ".config" / "turnup-linux"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

CONFIG_FILE = CONFIG_DIR / "turnup_config.json"
PROJECT_ROOT = Path(__file__).resolve().parent
APP_VERSION = "1.1.2"
APP_NAME = "Turn Up Linux"
APP_ID = "turnup-linux"
LATEST_RELEASE_URL = "https://api.github.com/repos/JacobSwierstra/turnup-linux/releases/latest"
PORT = "/dev/ttyACM0"
BAUD = 115200
VOLUME_STEP = 2
BUTTON_DEBOUNCE_SECONDS = 0.2
LED_REFRESH_SECONDS = 0.1
APP_CONTROL_REFRESH_SECONDS = 0.25
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
DEFAULT_MUTED_LED_COLOR = "#080B10"
BUTTON_ACTIONS = {"No action": "none", "Mute": "mute", "Play/Pause media": "play_pause"}
DEFAULT_BUTTON_ACTION = "mute"
BUILTIN_APP_TARGETS = {
    "Discord Voice": "WEBRTC VoiceEngine",
    "Firefox": "Firefox",
    "Helldivers 2": "Helldivers 2",
    "Line In / Capture": "70",
    "Master Volume": "@DEFAULT_AUDIO_SINK@",
    "Microphone": "@DEFAULT_AUDIO_SOURCE@",
    "Spotify": (
        "Spotify",
        "Spotify Free",
        "Spotify Premium",
        "Spotify Web Player",
        "librespot",
        "spotifyd",
        "com.spotify.client",
        "com.spotify.Client",
        "spotify.exe",
    ),
    "Steam": "Steam",
}
APP_TARGETS = dict(BUILTIN_APP_TARGETS)

DESKTOP_INCLUDE_CATEGORIES = {
    "Audio",
    "AudioVideo",
    "Game",
    "Player",
    "Recorder",
    "Telephony",
    "Video",
    "WebBrowser",
}
DESKTOP_EXCLUDE_CATEGORIES = {
    "Core",
    "DesktopSettings",
    "Filesystem",
    "PackageManager",
    "Settings",
    "System",
    "Utility",
}
AUDIO_APP_KEYWORDS = {
    "browser",
    "chrome",
    "chromium",
    "discord",
    "firefox",
    "game",
    "media",
    "music",
    "player",
    "signal",
    "slack",
    "spotify",
    "steam",
    "teams",
    "video",
    "vlc",
    "voice",
    "zoom",
}
IGNORED_STREAM_NAMES = {
    "audio stream",
    "dummy output",
    "pipewire",
    "wireplumber",
}
IGNORED_DESKTOP_APP_NAMES = {"Turn Up", "Turn Up Linux"}


class AppIndicatorTrayIcon:
    def __init__(self, root, show_callback, quit_callback):
        import gi

        gi.require_version("Gtk", "3.0")
        try:
            gi.require_version("AppIndicator3", "0.1")
            from gi.repository import AppIndicator3 as IndicatorModule
        except ValueError:
            gi.require_version("AyatanaAppIndicator3", "0.1")
            from gi.repository import AyatanaAppIndicator3 as IndicatorModule
        from gi.repository import GLib, Gtk

        initialized = Gtk.init_check()
        if isinstance(initialized, tuple):
            initialized = initialized[0]
        if not initialized:
            raise RuntimeError("GTK could not connect to the desktop session.")

        icon_path = tray_icon_path()
        icon_name = str(icon_path) if icon_path is not None else "audio-volume-high"
        self._loop = GLib.MainLoop()
        self._indicator_module = IndicatorModule
        self._indicator = IndicatorModule.Indicator.new(
            APP_ID, icon_name, IndicatorModule.IndicatorCategory.APPLICATION_STATUS
        )
        self._indicator.set_title(APP_NAME)
        self._indicator.set_status(IndicatorModule.IndicatorStatus.ACTIVE)

        menu = Gtk.Menu()
        show_item = Gtk.MenuItem(label=f"Show {APP_NAME}")
        show_item.connect("activate", lambda *_args: root.after(0, show_callback))
        menu.append(show_item)
        quit_item = Gtk.MenuItem(label="Quit")
        quit_item.connect("activate", lambda *_args: root.after(0, quit_callback))
        menu.append(quit_item)
        menu.show_all()
        self._indicator.set_menu(menu)
        self._menu = menu
        self._thread = threading.Thread(target=self._loop.run, daemon=True)
        self._thread.start()

    def stop(self):
        self._indicator.set_status(self._indicator_module.IndicatorStatus.PASSIVE)
        self._loop.quit()


def tray_icon_path():
    candidates = (
        PROJECT_ROOT / "data" / "turnup.svg",
        Path("/usr/share/icons/hicolor/scalable/apps/turnup.svg"),
        Path("/usr/local/share/icons/hicolor/scalable/apps/turnup.svg"),
    )
    return next((path for path in candidates if path.is_file()), None)


def build_pil_app_icon(size=64):
    from PIL import Image, ImageDraw

    scale = size / 256
    image = Image.new("RGBA", (size, size), (17, 24, 39, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (0, 0, size, size),
        radius=round(48 * scale),
        fill="#111827",
    )
    draw.rounded_rectangle(
        (
            round(28 * scale),
            round(28 * scale),
            round(228 * scale),
            round(228 * scale),
        ),
        radius=round(36 * scale),
        fill="#2563eb",
    )
    for left, top, right, bottom in (
        (66, 128, 94, 190),
        (114, 92, 142, 190),
        (162, 56, 190, 190),
    ):
        draw.rounded_rectangle(
            (
                round(left * scale),
                round(top * scale),
                round(right * scale),
                round(bottom * scale),
            ),
            radius=max(1, round(8 * scale)),
            fill="#ffffff",
        )
    return image


def build_tk_app_icon(size=64):
    try:
        from PIL import ImageTk

        return ImageTk.PhotoImage(build_pil_app_icon(size))
    except Exception:
        pixels = bytearray()
        for y in range(size):
            for x in range(size):
                source_x = x * 256 / size
                source_y = y * 256 / size
                color = (17, 24, 39)
                if 28 <= source_x <= 228 and 28 <= source_y <= 228:
                    color = (37, 99, 235)
                if (
                    66 <= source_x <= 94 and 128 <= source_y <= 190
                    or 114 <= source_x <= 142 and 92 <= source_y <= 190
                    or 162 <= source_x <= 190 and 56 <= source_y <= 190
                ):
                    color = (255, 255, 255)
                pixels.extend(color)
        ppm = f"P6\n{size} {size}\n255\n".encode("ascii") + pixels
        return tk.PhotoImage(data=ppm, format="PPM")


def run_git(project_root, *arguments):
    try:
        return subprocess.run(
            ["git", "-C", str(project_root), *arguments],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return None, str(error)


def normalized_version(value):
    return str(value).strip().lower().lstrip("v")


def fetch_latest_release(url=LATEST_RELEASE_URL):
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"turnup-linux/{APP_VERSION}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            release = json.load(response)
    except (OSError, urllib.error.URLError, ValueError) as error:
        return None, str(error)

    tag = str(release.get("tag_name", "")).strip()
    if not tag:
        return None, "GitHub's latest release does not have a version tag."
    assets = [
        {
            "name": str(asset.get("name", "")),
            "url": str(asset.get("browser_download_url", "")),
        }
        for asset in release.get("assets", [])
        if asset.get("name") and asset.get("browser_download_url")
    ]
    return {"tag": tag, "url": release.get("html_url", ""), "assets": assets}, ""


def check_for_release_update(current_version=APP_VERSION):
    release, error = fetch_latest_release()
    if release is None:
        return {"status": "error", "message": error}
    if normalized_version(release["tag"]) == normalized_version(current_version):
        return {"status": "current", "version": current_version, "release": release}
    return {
        "status": "update_available",
        "current_version": current_version,
        "release": release,
    }


def package_update_asset(release):
    assets = release.get("assets", [])
    if shutil.which("dnf"):
        suffixes = (".rpm",)
        command = lambda path: ["pkexec", "dnf", "install", "-y", path]
    elif shutil.which("apt"):
        suffixes = (".deb",)
        command = lambda path: ["pkexec", "apt", "install", "-y", path]
    elif shutil.which("pacman"):
        suffixes = (".pkg.tar.zst", ".pkg.tar.xz")
        command = lambda path: ["pkexec", "pacman", "-U", "--noconfirm", path]
    else:
        return None, None

    for asset in assets:
        lowered_name = asset["name"].lower()
        if lowered_name.endswith(".src.rpm"):
            continue
        if lowered_name.endswith(suffixes):
            return asset, command
    return None, command


def download_release_asset(asset):
    filename = Path(asset["name"]).name
    suffix = "".join(Path(filename).suffixes)
    temporary = tempfile.NamedTemporaryFile(
        prefix="turnup-update-", suffix=suffix, delete=False
    )
    destination = Path(temporary.name)
    temporary.close()
    request = urllib.request.Request(
        asset["url"], headers={"User-Agent": f"turnup-linux/{APP_VERSION}"}
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            with destination.open("wb") as output:
                shutil.copyfileobj(response, output)
    except (OSError, urllib.error.URLError) as error:
        destination.unlink(missing_ok=True)
        return None, str(error)
    return destination, ""


def install_package_release(release):
    asset, command_builder = package_update_asset(release)
    if command_builder is None:
        return False, "No supported package manager was found."
    if asset is None:
        return False, "This GitHub Release has no package for this Linux distribution."
    if shutil.which("pkexec") is None:
        return False, "pkexec is required to authorize the package installation."

    package_path, error = download_release_asset(asset)
    if package_path is None:
        return False, error
    try:
        result = subprocess.run(
            command_builder(str(package_path)), capture_output=True, text=True, check=False
        )
    except OSError as error:
        return False, str(error)
    finally:
        package_path.unlink(missing_ok=True)

    if result.returncode != 0:
        return False, result.stderr.strip() or result.stdout.strip() or "Package update failed."
    return True, result.stdout.strip()


def install_release_update(release, project_root=PROJECT_ROOT):
    if not (Path(project_root) / ".git").exists():
        return install_package_release(release)

    dirty = run_git(project_root, "status", "--porcelain")
    if isinstance(dirty, tuple):
        return False, dirty[1]
    if dirty.returncode != 0:
        return False, dirty.stderr.strip() or "Could not inspect local changes."
    if dirty.stdout.strip():
        return False, "Local changes must be committed or removed before updating."

    tag = release["tag"]
    fetch = run_git(project_root, "fetch", "--quiet", "--tags", "origin")
    if isinstance(fetch, tuple):
        return False, fetch[1]
    if fetch.returncode != 0:
        return False, fetch.stderr.strip() or "Could not fetch release tags."

    release_commit = run_git(project_root, "rev-parse", f"refs/tags/{tag}^{{commit}}")
    if isinstance(release_commit, tuple) or release_commit.returncode != 0:
        return False, f"Release tag {tag} was not found in the Git repository."

    result = run_git(project_root, "merge", "--ff-only", release_commit.stdout.strip())
    if isinstance(result, tuple):
        return False, result[1]
    if result.returncode != 0:
        return False, result.stderr.strip() or result.stdout.strip() or "Release update failed."
    return True, result.stdout.strip()



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
    command = (
        f"{desktop_exec_argument(python_executable)} "
        f"{desktop_exec_argument(script_path)} --minimized"
    )
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={APP_NAME}\n"
        "Comment=Start the Turn Up Linux audio controller\n"
        f"Exec={command}\n"
        f"Icon={APP_ID}\n"
        "Terminal=false\n"
        f"StartupWMClass={APP_ID}\n"
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
        "_muted_led_colors": {knob: DEFAULT_MUTED_LED_COLOR for knob in KNOBS},
        "_button_actions": {knob: DEFAULT_BUTTON_ACTION for knob in KNOBS},
        "_controller_positions": {},
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
    if value == "pause":
        return "play_pause"
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
            config[knob] = [
                value for value in values if isinstance(value, str) and value.strip()
            ]

    names = saved.get("_program_names", {})
    if isinstance(names, dict):
        config["_program_names"] = {
            key: value.strip()
            for key, value in names.items()
            if isinstance(key, str) and isinstance(value, str) and value.strip()
        }

    colors = saved.get("_led_colors", {})
    if isinstance(colors, dict):
        config["_led_colors"] = {
            knob: normalize_color(colors.get(knob, DEFAULT_LED_COLOR))
            for knob in KNOBS
        }

    muted_colors = saved.get("_muted_led_colors", {})
    if isinstance(muted_colors, dict):
        config["_muted_led_colors"] = {
            knob: normalize_color(muted_colors.get(knob, DEFAULT_MUTED_LED_COLOR))
            for knob in KNOBS
        }

    actions = saved.get("_button_actions", {})
    if isinstance(actions, dict):
        config["_button_actions"] = {
            knob: normalize_button_action(actions.get(knob, DEFAULT_BUTTON_ACTION))
            for knob in KNOBS
        }

    positions = saved.get("_controller_positions", {})
    if isinstance(positions, dict):
        config["_controller_positions"] = {
            knob: max(0, min(100, round(value)))
            for knob, value in positions.items()
            if knob in KNOBS and isinstance(value, (int, float))
        }
    return config


def write_config(config):
    temporary_file = CONFIG_FILE.with_suffix(".tmp")
    with temporary_file.open("w", encoding="utf-8") as config_file:
        json.dump(config, config_file, indent=4)
        config_file.write("\n")
    temporary_file.replace(CONFIG_FILE)


def desktop_application_dirs(data_home=None, data_dirs=None):
    home = Path(data_home or os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    shared = data_dirs or os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share")
    directories = [home / "applications"]
    directories.extend(Path(path) / "applications" for path in shared.split(":") if path)
    directories.extend(
        (
            Path.home() / ".local/share/flatpak/exports/share/applications",
            Path("/var/lib/flatpak/exports/share/applications"),
        )
    )
    return list(dict.fromkeys(directories))


def _desktop_bool(section, key):
    return section.get(key, "false").strip().lower() == "true"


def _desktop_search_terms(section):
    values = [section.get("Name", ""), section.get("StartupWMClass", "")]
    command = section.get("Exec", "")
    try:
        command_parts = shlex.split(command)
    except ValueError:
        command_parts = command.split()
    executable = next(
        (
            part
            for part in command_parts
            if not part.startswith(("%", "-")) and "=" not in part
        ),
        "",
    )
    if executable:
        values.append(Path(executable).name)
    values.extend((section.get("X-Flatpak", ""), section.get("Icon", "")))
    return tuple(dict.fromkeys(value.strip() for value in values if value.strip()))


def is_audio_desktop_app(section):
    if (
        section.get("Type", "Application") != "Application"
        or section.get("Name", "").strip() in IGNORED_DESKTOP_APP_NAMES
        or _desktop_bool(section, "Hidden")
        or _desktop_bool(section, "NoDisplay")
        or _desktop_bool(section, "Terminal")
    ):
        return False

    categories = {value for value in section.get("Categories", "").split(";") if value}
    searchable = " ".join(
        (
            section.get("Name", ""),
            section.get("GenericName", ""),
            section.get("Comment", ""),
            section.get("Exec", ""),
            section.get("Keywords", ""),
        )
    ).lower()
    keyword_match = any(keyword in searchable for keyword in AUDIO_APP_KEYWORDS)
    if categories & DESKTOP_EXCLUDE_CATEGORIES:
        return False
    return bool(categories & DESKTOP_INCLUDE_CATEGORIES) or keyword_match


def discover_desktop_apps(directories=None):
    discovered = {}
    for directory in desktop_application_dirs() if directories is None else directories:
        if not directory.is_dir():
            continue
        for desktop_file in directory.glob("*.desktop"):
            parser = configparser.ConfigParser(interpolation=None, strict=False)
            try:
                parser.read(desktop_file, encoding="utf-8")
                section = parser["Desktop Entry"]
            except (OSError, UnicodeError, KeyError, configparser.Error):
                continue
            name = section.get("Name", "").strip()
            if not name or not is_audio_desktop_app(section):
                continue
            terms = _desktop_search_terms(section)
            if terms:
                discovered.setdefault(name, terms)
    return discovered


def discover_audio_streams(status):
    discovered = {}
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
        match = re.match(r"^[^0-9]*\d+\.\s+(.+?)(?:\s+\[.*)?$", stripped)
        if match is None:
            continue
        name = match.group(1).strip()
        if name and name.lower() not in IGNORED_STREAM_NAMES:
            discovered.setdefault(name, (name,))
    return discovered


def discover_app_targets(status=None, directories=None):
    targets = dict(BUILTIN_APP_TARGETS)
    for name, terms in discover_desktop_apps(directories).items():
        targets.setdefault(name, terms)
    for name, terms in discover_audio_streams(
        get_audio_status() if status is None else status
    ).items():
        targets.setdefault(name, terms)
    return targets


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


def actionable_controller_events(events, syncing):
    if not syncing:
        return events
    return [event for event in events if event[0] != "button"]


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


def target_search_terms(target):
    real_target = APP_TARGETS.get(target, target)
    if isinstance(real_target, (tuple, list)):
        return [str(value).lower() for value in real_target if str(value).strip()]
    return [str(real_target).lower()]


def target_audio_value(target):
    real_target = APP_TARGETS.get(target, target)
    if isinstance(real_target, (tuple, list)):
        return str(real_target[0]) if real_target else ""
    return str(real_target)


def get_stream_ids(targets, status):
    resolved = {target: [] for target in targets}
    searchable = {}

    for target in targets:
        real_target = target_audio_value(target)

        if isinstance(real_target, str) and (
            real_target.startswith("@DEFAULT_AUDIO_") or real_target.isdigit()
        ):
            resolved[target] = [real_target]
        else:
            searchable[target] = target_search_terms(target)

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
        for target, search_terms in searchable.items():
            if any(search_name in lowered for search_name in search_terms):
                resolved[target].append(stream_id)

    if "Spotify" in resolved and not resolved["Spotify"]:
        resolved["Spotify"] = get_spotify_pactl_fallback()

    return resolved


def get_stream_volume_percentages(status):
    volumes = {}
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

        match = re.match(r"^[^0-9]*(\d+)\.\s+.+?\[vol:\s*([0-9.]+)", stripped)
        if match is None:
            continue
        volumes[match.group(1)] = max(0, min(100, round(float(match.group(2)) * 100)))
    return volumes


def target_percent_for_app(config, last_percent, app_name, fallback_percent=None):
    for knob in KNOBS:
        if app_name in config.get(knob, []):
            percent = last_percent.get(knob)
            if percent is not None:
                return percent
    return fallback_percent


def get_new_stream_volume_updates(
    config, last_percent, known_stream_ids, status, fallback_percent=None
):
    fallback_percent = fallback_percent or {}
    targets = {
        app_name
        for knob in KNOBS
        for app_name in config.get(knob, [])
    }
    resolved = get_stream_ids(targets, status)
    current_stream_ids = {
        app_name: set(stream_ids) for app_name, stream_ids in resolved.items()
    }
    updates = []

    for knob in KNOBS:
        for app_name in config.get(knob, []):
            percent = target_percent_for_app(
                config, last_percent, app_name, fallback_percent.get(app_name)
            )
            if percent is None:
                continue
            previous_ids = known_stream_ids.get(app_name, set())
            for stream_id in current_stream_ids.get(app_name, set()) - previous_ids:
                updates.append((stream_id, percent))

    return current_stream_ids, updates

def get_spotify_pactl_fallback():
    result = subprocess.run(
        ["pactl", "list", "short", "sink-inputs"],
        capture_output=True,
        text=True
    )

    for line in result.stdout.splitlines():
        sink_id = line.split()[0]
        return [f"pactl:{sink_id}"]

    return []

def get_pactl_sink_inputs(search_terms):
    ids = []

    result = subprocess.run(
        ["pactl", "list", "short", "sink-inputs"],
        capture_output=True,
        text=True
    )

    for line in result.stdout.splitlines():
        lower = line.lower()

        if any(term.lower() in lower for term in search_terms):
            sink_id = line.split()[0]
            ids.append(f"pactl:{sink_id}")

    return ids

def set_volume(target, percent):
    if str(target).startswith("pactl:"):
        sink_input = str(target).split(":", 1)[1]
        subprocess.run(
            ["pactl", "set-sink-input-volume", sink_input, f"{percent}%"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        return

    subprocess.run(
        ["wpctl", "set-volume", target, f"{percent}%"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )


def set_muted(target, muted):
    if str(target).startswith("pactl:"):
        sink_input = str(target).split(":", 1)[1]
        command = ["pactl", "set-sink-input-mute", sink_input, "1" if muted else "0"]
    else:
        command = ["wpctl", "set-mute", target, "1" if muted else "0"]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return False, str(error)
    return result.returncode == 0, result.stderr.strip()


def set_media_play_pause():
    try:
        daemon = subprocess.run(
            ["playerctld", "daemon"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if daemon.returncode != 0:
            return False, daemon.stderr.strip() or "Could not start playerctld."

        result = subprocess.run(
            ["playerctl", "--player=playerctld", "play-pause"],
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
    def __init__(self, root, start_minimized=False):
        self.root = root
        self.config = load_config()
        self.config_lock = threading.Lock()
        self.stop_event = threading.Event()
        self.controller_thread = None
        self.last_percent = dict(self.config["_controller_positions"])
        self.last_app_percent = {}
        self.last_button_press = {}
        self.channel_muted = {knob: False for knob in KNOBS}
        self.listboxes = {}
        self.color_buttons = {}
        self.muted_color_buttons = {}
        self.button_action_vars = {}
        self.settings_menu = None
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
        self.tray_icon = None
        self.exiting = False
        self.update_in_progress = False

        self._configure_window()
        self._build_ui()
        self.refresh_apps(show_status=False)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        tray_ready = self._ensure_tray_icon()
        if start_minimized and tray_ready:
            self.root.withdraw()
        self.root.after(350, self.start_controller)

    def _configure_window(self):
        self.root.title(APP_NAME)
        self.root.iconname(APP_NAME)
        try:
            self.window_icon = build_tk_app_icon(64)
            self.root.iconphoto(True, self.window_icon)
        except Exception:
            self.window_icon = None
        try:
            self.root.tk.call("tk", "appname", APP_NAME)
        except tk.TclError:
            pass
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
        ttk.Label(title_row, text=APP_NAME, style="Title.TLabel").pack(side="left")
        menu_button = ttk.Menubutton(title_row, text="Settings", style="Secondary.TButton")
        settings_menu = tk.Menu(menu_button, tearoff=False)
        self.settings_menu = settings_menu
        settings_menu.add_command(label="Restart Controller", command=self.restart_controller)
        settings_menu.add_command(label="Refresh App List", command=self.refresh_apps)
        settings_menu.add_command(label="Check for Updates", command=self.check_for_updates)
        settings_menu.add_separator()
        settings_menu.add_checkbutton(
            label="Start with Linux minimized to tray",
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
                text=f"Active Color  {color}",
                command=lambda selected_knob=knob: self.choose_led_color(
                    selected_knob, muted=False
                ),
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

            muted_color = self.config["_muted_led_colors"][knob]
            muted_color_button = tk.Button(
                options,
                text=f"Muted Color  {muted_color}",
                command=lambda selected_knob=knob: self.choose_led_color(
                    selected_knob, muted=True
                ),
                bg=muted_color,
                fg=self._contrast_text_color(muted_color),
                activebackground=muted_color,
                activeforeground=self._contrast_text_color(muted_color),
                relief="flat",
                borderwidth=0,
                padx=10,
                pady=6,
            )
            muted_color_button.pack(fill="x", pady=(8, 0))
            self.muted_color_buttons[knob] = muted_color_button

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
            if enabled and not self._ensure_tray_icon():
                self.autostart_var.set(False)
                return
            set_autostart_enabled(enabled)
        except OSError as error:
            self.autostart_var.set(is_autostart_enabled())
            messagebox.showerror("Startup setting failed", str(error), parent=self.root)
            self.status_var.set("Could not update startup setting")
            return
        state = "enabled" if enabled else "disabled"
        self.status_var.set(f"Start with Linux {state}")

    def check_for_updates(self):
        if self.update_in_progress:
            return
        self.update_in_progress = True
        self.status_var.set("Checking GitHub for updates...")
        threading.Thread(target=self._check_for_updates_worker, daemon=True).start()

    def _check_for_updates_worker(self):
        result = check_for_release_update()
        self.root.after(0, self._handle_update_check, result)

    def _handle_update_check(self, result):
        self.update_in_progress = False
        status = result["status"]

        if status == "current":
            self.status_var.set("Turn Up is up to date")
            messagebox.showinfo(
                "No updates available",
                f"Turn Up {APP_VERSION} matches the latest published GitHub Release.",
                parent=self.root,
            )
            return

        if status == "error":
            self.status_var.set("Update check failed")
            messagebox.showerror("Update check failed", result["message"], parent=self.root)
            return

        release = result["release"]
        should_update = messagebox.askyesno(
            "Update available",
            f"A new GitHub Release is available ({APP_VERSION} -> {release['tag']}).\n\n"
            "Download and install it now?",
            parent=self.root,
        )
        if not should_update:
            self.status_var.set("Update available")
            return

        self.update_in_progress = True
        self.status_var.set("Downloading and installing update...")
        threading.Thread(
            target=self._install_update_worker, args=(release,), daemon=True
        ).start()

    def _install_update_worker(self, release):
        success, message = install_release_update(release)
        self.root.after(0, self._handle_update_install, success, message)

    def _handle_update_install(self, success, message):
        self.update_in_progress = False
        if not success:
            self.status_var.set("Update installation failed")
            messagebox.showerror("Update failed", message, parent=self.root)
            return

        self.status_var.set("Update installed")
        if messagebox.askyesno(
            "Update installed",
            f"The update was installed successfully. Restart {APP_NAME} now?",
            parent=self.root,
        ):
            self.restart_application()

    def restart_application(self):
        self.save_config()
        self.stop_event.set()
        self._stop_tray_icon()
        self.root.destroy()
        os.execv(sys.executable, [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]])

    def _ensure_tray_icon(self):
        if self.tray_icon is not None:
            return True

        if os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland":
            try:
                self.tray_icon = AppIndicatorTrayIcon(
                    self.root, self.show_window, self.exit_app
                )
                return True
            except Exception:
                self.tray_icon = None

        try:
            import pystray
            image = build_pil_app_icon(64)
        except Exception as error:
            messagebox.showerror(
                "System tray support unavailable",
                f"{APP_NAME} could not create a system tray icon. Install GTK AppIndicator "
                f"or pystray support for your desktop.\n\n{error}",
                parent=self.root,
            )
            self.root.deiconify()
            return False

        self.tray_icon = pystray.Icon(
            APP_ID,
            image,
            APP_NAME,
            pystray.Menu(
                pystray.MenuItem(f"Show {APP_NAME}", self._tray_show, default=True),
                pystray.MenuItem("Quit", self._tray_quit),
            ),
        )
        self.tray_icon.run_detached()
        return True

    def _tray_show(self, _icon=None, _item=None):
        self.root.after(0, self.show_window)

    def _tray_quit(self, _icon=None, _item=None):
        self.root.after(0, self.exit_app)

    def show_window(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _stop_tray_icon(self):
        icon = self.tray_icon
        self.tray_icon = None
        if icon is not None:
            icon.stop()

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
            color = (
                self.config["_muted_led_colors"][item]
                if muted
                else self.config["_led_colors"][item]
            )
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
        APP_TARGETS.clear()
        APP_TARGETS.update(discover_app_targets())
        for saved_apps in self.config_snapshot().values():
            for app_name in saved_apps:
                APP_TARGETS.setdefault(app_name, app_name)
        self.ordered_apps = sorted(APP_TARGETS, key=lambda app: self.display_name(app).lower())

        for knob, listbox in self.listboxes.items():
            selected = selected_by_knob[knob] or set(self.config.get(knob, []))
            listbox.delete(0, tk.END)
            for index, app_name in enumerate(self.ordered_apps):
                listbox.insert(tk.END, self.display_name(app_name))
                if app_name in selected:
                    listbox.selection_set(index)

        if show_status:
            self.status_var.set(f"Found {len(self.ordered_apps)} audio-capable programs")

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

    def _set_led_color(self, knob, color, muted=False):
        color = normalize_color(color)
        config_key = "_muted_led_colors" if muted else "_led_colors"
        buttons = self.muted_color_buttons if muted else self.color_buttons
        label = "Muted Color" if muted else "Active Color"
        with self.config_lock:
            self.config[config_key][knob] = color
        button = buttons[knob]
        text_color = self._contrast_text_color(color)
        button.configure(
            text=f"{label}  {color}",
            bg=color,
            fg=text_color,
            activebackground=color,
            activeforeground=text_color,
        )
        self.update_controller_preview(knob)

    def choose_led_color(self, knob, muted=False):
        config_key = "_muted_led_colors" if muted else "_led_colors"
        label = "Muted LED Color" if muted else "Active LED Color"
        current = self.config[config_key][knob]
        dialog = ColorWheelDialog(
            self.root,
            f"Channel {KNOBS.index(knob) + 1} {label}",
            current,
            lambda color: self._set_led_color(knob, color, muted=muted),
        )
        if dialog.result is None:
            self._set_led_color(knob, current, muted=muted)
            return

        selected = dialog.result
        self._set_led_color(knob, selected, muted=muted)
        self.save_config()
        state = "muted" if muted else "active"
        self.status_var.set(
            f"Channel {KNOBS.index(knob) + 1} {state} LED color set to {selected}"
        )

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
        self.config["_controller_positions"] = self.last_percent.copy()

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
                color_to_rgb(self.config["_muted_led_colors"][knob])
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

    def handle_button_press(self, knob, channel, controller, now=None):
        with self.config_lock:
            button_action = self.config["_button_actions"][knob]
        if button_action == "none":
            return

        now = time.monotonic() if now is None else now
        if now - self.last_button_press.get(knob, 0) < BUTTON_DEBOUNCE_SECONDS:
            return
        self.last_button_press[knob] = now

        if button_action == "play_pause":
            success, message = set_media_play_pause()
            if success:
                self.set_status(f"Channel {channel + 1} toggled media play/pause")
            else:
                self.set_status(f"Channel {channel + 1} play/pause failed: {message}")
            return

        muted = not self.channel_muted[knob]
        success, message = self.apply_mute_update(knob, muted)
        if success:
            self.channel_muted[knob] = muted
            set_channel_leds(controller, self.led_colors_snapshot())
            self.root.after(0, self.update_controller_preview, knob)
            state = "muted" if muted else "unmuted"
            self.set_status(f"Channel {channel + 1} {state}")
            return

        action = "mute" if muted else "unmute"
        self.set_status(f"Channel {channel + 1} {action} failed: {message}")

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
            set_channel_leds(controller, self.led_colors_snapshot())
            self.set_status("Syncing controller state...")
            buffer = b""
            synced_channels = set()
            syncing = True
            sync_started = time.monotonic()
            next_led_refresh = time.monotonic() + LED_REFRESH_SECONDS
            config = self.config_snapshot()
            mapped_apps = {
                app_name
                for knob in KNOBS
                for app_name in config.get(knob, [])
            }
            audio_status = get_audio_status()
            known_stream_ids = {
                app_name: set(stream_ids)
                for app_name, stream_ids in get_stream_ids(
                    mapped_apps, audio_status
                ).items()
            }
            self.remember_app_volumes(config, known_stream_ids, audio_status)
            if self.last_percent:
                self.apply_volume_updates(self.last_percent.copy())
            next_app_control_refresh = time.monotonic() + APP_CONTROL_REFRESH_SECONDS

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
                for event_type, channel, value in actionable_controller_events(
                    events, syncing
                ):
                    knob = f"channel_{channel}"
                    if knob not in KNOBS:
                        continue
                    if event_type == "button":
                        self.handle_button_press(knob, channel, controller, now)
                        continue

                    percent = max(0, min(100, round((value / 1023) * 100)))
                    if syncing:
                        self.last_percent[knob] = percent
                        updates[knob] = percent
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

                if syncing and now - sync_started >= INITIALIZATION_TIMEOUT_SECONDS:
                    syncing = False
                    self.root.after(0, self.finish_initialization)

                if now >= next_app_control_refresh:
                    known_stream_ids = self.apply_new_stream_volumes(known_stream_ids)
                    next_app_control_refresh = now + APP_CONTROL_REFRESH_SECONDS
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

    def apply_new_stream_volumes(self, known_stream_ids):
        config = self.config_snapshot()
        status = get_audio_status()
        current_stream_ids, updates = get_new_stream_volume_updates(
            config,
            self.last_percent.copy(),
            known_stream_ids,
            status,
            self.last_app_percent.copy(),
        )
        for stream_id, percent in updates:
            set_volume(stream_id, percent)
        self.remember_app_volumes(config, current_stream_ids, status, updates)
        return current_stream_ids

    def remember_app_volumes(self, config, current_stream_ids, status, updates=()):
        stream_volumes = get_stream_volume_percentages(status)
        applied_volumes = dict(updates)

        for app_name, stream_ids in current_stream_ids.items():
            percent = target_percent_for_app(config, self.last_percent, app_name)
            if percent is None:
                percent = next(
                    (
                        applied_volumes[stream_id]
                        for stream_id in stream_ids
                        if stream_id in applied_volumes
                    ),
                    None,
                )
            if percent is None:
                percent = next(
                    (
                        stream_volumes[stream_id]
                        for stream_id in stream_ids
                        if stream_id in stream_volumes
                    ),
                    None,
                )
            if percent is not None:
                self.last_app_percent[app_name] = percent

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

    def _hide_open_menus(self):
        settings_menu = getattr(self, "settings_menu", None)
        if settings_menu is None:
            return
        try:
            settings_menu.unpost()
        except tk.TclError:
            pass

    def close(self):
        self._hide_open_menus()
        if self._ensure_tray_icon():
            self.save_config()
            self.root.withdraw()
            self.status_var.set(f"{APP_NAME} is running in the system tray")
            return
        self.exit_app()

    def exit_app(self):
        if self.exiting:
            return
        self.exiting = True
        self._hide_open_menus()
        self.save_config()
        self.stop_event.set()
        if self.initialization_watchdog is not None:
            self.root.after_cancel(self.initialization_watchdog)
            self.initialization_watchdog = None
        self._stop_tray_icon()
        self.root.destroy()


def main():
    root = tk.Tk(className=APP_ID)
    TurnUpApp(root, start_minimized="--minimized" in sys.argv[1:])
    root.mainloop()


if __name__ == "__main__":
    main()
