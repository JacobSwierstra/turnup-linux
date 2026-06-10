import json
import subprocess
import threading
import time
import serial
import tkinter as tk

CONFIG_FILE = "turnup_config.json"
PORT = "/dev/ttyACM0"
BAUD = 115200

KNOBS = ["channel_0", "channel_1", "channel_2", "channel_3", "channel_4"]

DEFAULT_APPS = [
    "Master Volume",
    "Microphone",
    "Discord Voice",
    "Firefox",
    "Steam",
    "Spotify",
    "Helldivers 2",
    "WEBRTC VoiceEngine"
]

running = False
last_percent = {}


def get_apps():
    apps = list(DEFAULT_APPS)

    ignore_words = [
        "pipewire", "wireplumber", "kwin", "plasmashell",
        "xdg", "libcanberra", "uresourced", "wpctl",
        "input", "output", "monitor", "alsa", "v4l2",
        "camera", "portal"
    ]

    try:
        result = subprocess.run(["wpctl", "status"], capture_output=True, text=True)

        for line in result.stdout.splitlines():
            line = line.strip()

            if "." not in line or "[" not in line:
                continue

            name = line.split(".", 1)[1].split("[", 1)[0].strip()

            if not name or len(name) < 3:
                continue

            if any(word in name.lower() for word in ignore_words):
                continue

            apps.append(name)

    except Exception:
        pass

    return sorted(set(apps), key=str.lower)


def load_config():
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {knob: [] for knob in KNOBS}


def save_config():
    config = {}

    for knob, listbox in listboxes.items():
        selected = [listbox.get(i) for i in listbox.curselection()]
        config[knob] = selected

    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=4)

    status_label.config(text="Mappings saved")


def refresh_apps():
    apps = get_apps()

    for knob, listbox in listboxes.items():
        current_selection = [listbox.get(i) for i in listbox.curselection()]
        listbox.delete(0, tk.END)

        for app in apps:
            listbox.insert(tk.END, app)

        for index, app in enumerate(apps):
            if app in current_selection:
                listbox.selection_set(index)

    status_label.config(text="Apps refreshed")


def get_stream_ids_for_app(app_name):
    if app_name == "Master Volume":
        return ["@DEFAULT_AUDIO_SINK@"]

    if app_name == "Microphone":
        return ["@DEFAULT_AUDIO_SOURCE@"]

    search_name = app_name

    if app_name == "Discord Voice":
        search_name = "WEBRTC VoiceEngine"

    stream_ids = []

    result = subprocess.run(["wpctl", "status"], capture_output=True, text=True)
    lines = result.stdout.splitlines()

    in_audio_streams = False

    for line in lines:
        stripped = line.strip()

        if "Streams:" in stripped:
            in_audio_streams = True
            continue

        if in_audio_streams and stripped.startswith(("Video", "Settings")):
            break

        if in_audio_streams and search_name.lower() in stripped.lower():
            try:
                stream_id = stripped.split(".", 1)[0].strip()
                if stream_id.isdigit():
                    stream_ids.append(stream_id)
            except Exception:
                pass

    return stream_ids


def set_volume(target, percent):
    volume = f"{percent}%"

    subprocess.run(
        ["wpctl", "set-volume", target, volume],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )


def control_loop():
    global running

    try:
        ser = serial.Serial(PORT, BAUD, timeout=0.1)
    except Exception as e:
        status_label.config(text=f"Serial error: {e}")
        running = False
        return

    time.sleep(3)
    ser.reset_input_buffer()

    status_label.config(text="Controller running")

    while running:
        try:
            data = ser.read(64)

            if not data:
                continue

            i = 0

            while i < len(data) - 5:
                if data[i] == 0xFF and data[i + 1] == 0xFE and data[i + 2] == 0x03:
                    channel = data[i + 3]
                    value = (data[i + 4] << 8) | data[i + 5]
                    percent = round((value / 1023) * 100)

                    knob_name = f"channel_{channel}"

                    if last_percent.get(knob_name) != percent:
                        config = load_config()
                        targets = config.get(knob_name, [])

                        for app in targets:
                            stream_ids = get_stream_ids_for_app(app)

                            for stream_id in stream_ids:
                                set_volume(stream_id, percent)

                        last_percent[knob_name] = percent

                    i += 6
                else:
                    i += 1

        except Exception as e:
            status_label.config(text=f"Error: {e}")

    try:
        ser.close()
    except Exception:
        pass

    status_label.config(text="Controller stopped")


def start_controller():
    global running

    save_config()

    if running:
        status_label.config(text="Already running")
        return

    running = True
    thread = threading.Thread(target=control_loop, daemon=True)
    thread.start()


def stop_controller():
    global running
    running = False


config = load_config()

root = tk.Tk()
root.title("Turn Up Linux Mapper")
root.geometry("1100x500")

tk.Label(root, text="Turn Up Linux Mapper", font=("Arial", 18)).pack(pady=10)

main_frame = tk.Frame(root)
main_frame.pack(fill="both", expand=True)

apps = get_apps()
listboxes = {}

for knob in KNOBS:
    frame = tk.Frame(main_frame)
    frame.pack(side="left", fill="both", expand=True, padx=5)

    tk.Label(frame, text=knob, font=("Arial", 12)).pack()

    listbox = tk.Listbox(frame, selectmode="multiple", exportselection=False)
    listbox.pack(fill="both", expand=True)

    for app in apps:
        listbox.insert(tk.END, app)

    saved = config.get(knob, [])

    for index, app in enumerate(apps):
        if app in saved:
            listbox.selection_set(index)

    listboxes[knob] = listbox

button_frame = tk.Frame(root)
button_frame.pack(pady=10)

tk.Button(button_frame, text="Refresh Apps", command=refresh_apps).pack(side="left", padx=10)
tk.Button(button_frame, text="Save Mapping", command=save_config).pack(side="left", padx=10)

status_label = tk.Label(root, text="")
status_label.pack()

root.after(1000, start_controller)

root.mainloop()