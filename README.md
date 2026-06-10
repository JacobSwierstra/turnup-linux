# Turn Up Linux

Turn Up is a Linux GUI for controlling mapped application volumes, mute state, and the controller LEDs.

## Requirements

- Python 3
- Tkinter for Python
- PySerial
- `wpctl` from PipeWire / WirePlumber
- Access to the controller at `/dev/ttyACM0`

## Install

### 1. Get the code

```bash
git clone https://github.com/JacobSwierstra/turnup-linux.git
cd turnup-linux
```

### 2. Install dependencies

Install Python and the packages your distribution uses for Tkinter, serial support, and PipeWire control.

On Debian or Ubuntu systems, this is usually:

```bash
sudo apt install python3 python3-tk python3-pip python3-serial wireplumber pipewire
```

If your distro does not ship `python3-serial`, install PySerial with pip:

```bash
python3 -m pip install --user pyserial
```

### 3. Run the app

```bash
python3 turnup_gui.py
```

## Optional: start on login

Use the `Settings` menu in the top-right corner and enable `Start with Linux`.

## Notes

- The app expects the controller on `/dev/ttyACM0`.
- If the controller is not found, unplug it and reconnect it, then use `Restart Controller` from the `Settings` menu.
- Your mappings, LED colors, and button action choices are saved in `turnup_config.json`.
