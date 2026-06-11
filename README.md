# Turn Up Linux

Turn Up Linux is an unofficial Linux application for the TurnUp USB Mixer. It provides application volume control, device volume control, mute controls, RGB lighting configuration, profiles, and system tray integration.

This project is not affiliated with or endorsed by the TurnUp developers. It was created to bring Linux support to TurnUp mixer users.

## Features

* Application-specific volume control
* Device volume control
* RGB LED customization
* Profile and preset support
* System tray integration
* Start with Linux support
* Native Fedora RPM packaging
* Fedora COPR repository support

---

## Requirements

* Python 3
* Tkinter
* PySerial
* Pillow
* pystray
* PipeWire / WirePlumber
* Access to the controller at `/dev/ttyACM0`

---

Installation
Fedora / RHEL
sudo dnf copr enable ezswees/turnup
sudo dnf install turnup
Debian / Ubuntu / Linux Mint / Pop!_OS / Zorin

Download the latest .deb package from Releases and install:

sudo apt install ./turnup-*.deb
Arch Linux

Build and install using the included PKGBUILD:

makepkg -si
Other Linux Distributions

Use the installer script:

./install.sh

Requirements:

Python 3
PipeWire / WirePlumber
Tkinter
PySerial
Pillow
pystray

---

## Build Locally

Install the RPM build tools:

```bash
sudo dnf install rpm-build
```

From the repository root:

```bash
./packaging/rpm/build-rpm.sh
```

The build uses `build/rpmbuild/` as its private RPM build tree and copies the finished RPM package to the repository root.

---

## Install Local RPM

```bash
sudo dnf install ./turnup-1.0.0-1.fc44.noarch.rpm
```

Launch Turn Up from the desktop application menu or run:

```bash
turnup
```

---

## Uninstall

```bash
sudo dnf remove turnup
```

User settings stored in:

```text
~/.config/turnup-linux/
```

are intentionally retained when the RPM is removed.

---

## Run From Source

### 1. Clone the Repository

```bash
git clone https://github.com/JacobSwierstra/turnup-linux.git
cd turnup-linux
```

### 2. Install Dependencies

On Debian/Ubuntu systems:

```bash
sudo apt install python3 python3-tk python3-pip python3-serial wireplumber pipewire
```

If your distribution does not provide PySerial:

```bash
python3 -m pip install --user pyserial
```

Install tray dependencies if necessary:

```bash
python3 -m pip install --user pillow pystray
```

### 3. Run the Application

```bash
python3 turnup_gui.py
```

---

## Start With Linux

Use the Settings menu within Turn Up and enable **Start with Linux**.

When enabled:

* Turn Up starts automatically after login
* The application starts minimized to the system tray
* Closing the main window keeps the application running in the tray
* Use the tray menu's **Quit** option to fully exit the application

---

## Troubleshooting

### Controller Not Detected

The application expects the controller to be available at:

```text
/dev/ttyACM0
```

If the controller is not found:

1. Disconnect and reconnect the controller.
2. Open Turn Up.
3. Use **Settings → Restart Controller**.

### Serial Permissions

If the controller is detected but cannot be accessed, add your user to the appropriate serial device group and log out/in:

```bash
sudo usermod -aG dialout $USER
```

Some distributions may use a different group name.

### Application List Missing Programs

The application list is generated from:

* Installed desktop applications
* Active PipeWire audio streams

Launch the target application and refresh the list.

---

## Configuration Storage

Turn Up stores configuration under:

```text
~/.config/turnup-linux/
```

This includes:

* Application mappings
* LED colors
* Profiles and presets
* Button actions
* Startup preferences

---

## GitHub

Source code:

https://github.com/JacobSwierstra/turnup-linux

Releases:

https://github.com/JacobSwierstra/turnup-linux/releases

Issues and feature requests:

https://github.com/JacobSwierstra/turnup-linux/issues

---

## Contributing

Bug reports, feature requests, and pull requests are welcome.

If you encounter a problem, please include:

* Linux distribution and version
* Desktop environment
* Turn Up firmware version (if known)
* Relevant logs or screenshots

---

## License

See the repository license file for details.
