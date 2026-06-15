````md
# Turn Up Linux

Unofficial Linux support for the TurnUp USB Mixer.

Turn Up Linux brings native Linux support to the TurnUp mixer, providing per-application volume control, device management, RGB customization, media controls, profiles, and system tray integration using PipeWire and WirePlumber.

> This project is not affiliated with or endorsed by TurnUp. It is a community-developed Linux implementation for TurnUp mixer users.

---

## Features

| Feature | Status |
|----------|----------|
| Per-application volume control | ✅ |
| System audio control | ✅ |
| Microphone control | ✅ |
| Mute / unmute buttons | ✅ |
| RGB LED customization | ✅ |
| Profiles & presets | ✅ |
| Media controls (Play/Pause) | ✅ |
| System tray integration | ✅ |
| Start with Linux | ✅ |
| Automatic update checking | ✅ |
| Fedora COPR packages | ✅ |
| Debian packages | ✅ |
| Arch Linux support | ✅ |

---

## Screenshots

_Add screenshots or GIFs here._

---

## Supported Distributions

### Official Packages

- Fedora
- RHEL
- Rocky Linux
- AlmaLinux
- Debian
- Ubuntu
- Linux Mint
- Pop!_OS
- Zorin OS
- Arch Linux

### Generic Installation

Any Linux distribution with:

- Python 3
- PipeWire
- WirePlumber
- Tkinter
- PySerial
- Pillow
- pystray

---

# Installation

## Fedora / RHEL

```bash
sudo dnf copr enable ezswees/turnup
sudo dnf install turnup
````

## Debian / Ubuntu / Linux Mint / Pop!_OS / Zorin

Download the latest `.deb` package from the Releases page and install:

```bash
sudo apt install ./turnup-*.deb
```

## Arch Linux

Build and install using the included PKGBUILD:

```bash
makepkg -si
```

## Other Linux Distributions

Use the installer script:

```bash
./install.sh
```

---

# Quick Start

Launch Turn Up:

```bash
turnup
```

On first launch:

1. Connect your TurnUp controller.
2. Configure application mappings.
3. Adjust RGB lighting.
4. Save your preferred profile.
5. Enable **Start with Linux** if desired.

---

# Building Packages

## Build RPM

```bash
sudo dnf install rpm-build
./packaging/rpm/build-rpm.sh
```

Built RPMs will be placed in:

```text
build/rpmbuild/RPMS/noarch/
```

---

# Install Local RPM

```bash
sudo dnf install ./turnup-1.1.0-1.fc44.noarch.rpm
```

---

# Run From Source

## Clone the Repository

```bash
git clone https://github.com/JacobSwierstra/turnup-linux.git
cd turnup-linux
```

## Install Dependencies

### Debian / Ubuntu

```bash
sudo apt install \
    python3 \
    python3-tk \
    python3-pip \
    python3-serial \
    pipewire \
    wireplumber
```

### Additional Python Packages

```bash
python3 -m pip install --user pillow pystray
```

## Run

```bash
python3 turnup_gui.py
```

---

# Start With Linux

Enable **Settings → Start with Linux**.

When enabled:

* Starts automatically after login
* Starts minimized to the system tray
* Closing the window keeps Turn Up running
* Use **Quit** from the tray menu to fully exit

---

# Troubleshooting

## Controller Not Detected

The controller is expected to appear as:

```text
/dev/ttyACM0
```

Try:

1. Disconnect and reconnect the controller.
2. Restart Turn Up.
3. Use **Settings → Restart Controller**.

## Serial Permissions

Add your user to the serial device group:

```bash
sudo usermod -aG dialout $USER
```

Log out and back in afterward.

> Some distributions may use a different serial device group.

## Missing Applications

Turn Up discovers applications using:

* PipeWire audio streams
* Installed desktop applications

Launch the target application and refresh the list.

---

# Configuration

User settings are stored in:

```text
~/.config/turnup-linux/
```

Stored data includes:

* Application mappings
* RGB settings
* Profiles
* Presets
* Startup preferences
* Button actions

Configuration is intentionally preserved during upgrades and uninstallation.

---

# Uninstall

## Fedora / RHEL

```bash
sudo dnf remove turnup
```

Configuration files located in `~/.config/turnup-linux/` are retained.

---

# Project Links

## Repository

https://github.com/JacobSwierstra/turnup-linux

## Releases

https://github.com/JacobSwierstra/turnup-linux/releases

## Issue Tracker

https://github.com/JacobSwierstra/turnup-linux/issues

---

# Contributing

Bug reports, feature requests, and pull requests are welcome.

Please include:

* Linux distribution and version
* Desktop environment
* TurnUp firmware version (if known)
* Relevant logs or screenshots

---

# License

See the repository license file for details.

```
```
