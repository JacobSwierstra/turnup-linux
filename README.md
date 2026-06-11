# Turn Up Linux

Turn Up is a Linux GUI for controlling mapped application volumes, mute state, and the controller LEDs.

## Requirements

- Python 3
- Tkinter for Python
- PySerial
- Pillow and pystray (system tray support)
- `wpctl` from PipeWire / WirePlumber
- Access to the controller at `/dev/ttyACM0`

## Fedora RPM

The RPM installs these files:

```text
/usr/bin/turnup
/usr/share/turnup/turnup_gui.py
/usr/share/applications/turnup.desktop
/usr/share/icons/hicolor/scalable/apps/turnup.svg
```

### Build locally

Install the RPM build tools:

```bash
sudo dnf install rpm-build
```

From the repository root, run:

```bash
./packaging/rpm/build-rpm.sh
```

The build uses `build/rpmbuild/` as its private RPM build tree and copies the
finished binary package to the repository root as `turnup-*.rpm`.

### Install locally

```bash
sudo dnf install ./turnup-1.0.0-1.fc44.noarch.rpm
```

DNF installs the declared runtime dependencies: Python, Tkinter, PySerial,
Pillow, pystray, WirePlumber, PulseAudio utilities, and Playerctl.

Launch Turn Up from the desktop application search or run:

```bash
turnup
```

### Uninstall

```bash
sudo dnf remove turnup
```

User settings under `~/.config/turnup-linux/` are intentionally retained when
the RPM is removed.

## Run From Source

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

Install the tray dependencies with pip if your distribution does not package them:

```bash
python3 -m pip install --user pillow pystray
```

### 3. Run the app

```bash
python3 turnup_gui.py
```

## Optional: start on login

Use the `Settings` menu in the top-right corner and enable `Start with Linux`. Turn Up
will start minimized in the system tray. Closing its window while this option is enabled
also keeps it running in the tray; use the tray menu's `Quit` action to stop it.

## Notes

- The app expects the controller on `/dev/ttyACM0`.
- If the controller is not found, unplug it and reconnect it, then use `Restart Controller` from the `Settings` menu.
- The program list is scanned from installed desktop applications and active PipeWire streams.
- Your mappings, LED colors, and button action choices are saved under `~/.config/turnup-linux/`.
- The RPM is for local installation only and is not published to COPR.

## Future Packaging

Publishing Turn Up to Fedora COPR is planned so Fedora users can eventually install it with:

```bash
sudo dnf copr enable yourname/turnup
sudo dnf install turnup
```

The COPR repository does not exist yet. The GitHub release RPM is the supported installation
method for now.
