Name:           turnup
Version:        1.1.1
Release:        1%{?dist}
Summary:        Hardware controller for Linux application audio

License:        LicenseRef-Proprietary
URL:            https://github.com/JacobSwierstra/turnup-linux
Source0:        %{name}-%{version}.tar.gz

BuildArch:      noarch

Requires:       python3
Requires:       python3-gobject
Requires:       python3-pillow
Requires:       python3-pyserial
Requires:       python3-pystray
Requires:       python3-tkinter
Requires:       libappindicator-gtk3
Requires:       playerctl
Requires:       pulseaudio-utils
Requires:       wireplumber

%description
Turn Up is a Linux desktop application for mapping a hardware mixer to
application audio streams, controlling volume and mute state, and configuring
the controller LEDs.

%prep
%autosetup

%build
# The application is interpreted Python and does not require compilation.

%install
DESTDIR=%{buildroot} PREFIX=%{_prefix} ./install.sh

%files
%{_bindir}/turnup
%{_datadir}/turnup/
%{_datadir}/applications/turnup.desktop
%{_datadir}/icons/hicolor/scalable/apps/turnup.svg

%changelog
* Mon Jun 15 2026 Jacob Swierstra <jacobswierstra@users.noreply.github.com> - 1.1.1-1
- Ignore buffered controller button packets during startup synchronization

* Mon Jun 15 2026 Jacob Swierstra <jacobswierstra@users.noreply.github.com> - 1.1.0-1
- Add release-based in-app updates and native system tray support
- Sync newly launched application streams to current controller positions
- Fix mute toggling and route media controls to the most recently active player

* Thu Jun 11 2026 Jacob Swierstra <jacobswierstra@users.noreply.github.com> - 1.0.0-2
- Add shared installer and cross-distribution packaging support

* Thu Jun 11 2026 Jacob Swierstra <jacobswierstra@users.noreply.github.com> - 1.0.0-1
- Initial local Fedora RPM package
