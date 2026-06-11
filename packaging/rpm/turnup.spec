Name:           turnup
Version:        1.0.0
Release:        1%{?dist}
Summary:        Hardware controller for Linux application audio

License:        LicenseRef-Proprietary
URL:            https://github.com/JacobSwierstra/turnup-linux
Source0:        %{name}-%{version}.tar.gz

BuildArch:      noarch

Requires:       python3
Requires:       python3-pillow
Requires:       python3-pyserial
Requires:       python3-pystray
Requires:       python3-tkinter
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
mkdir -p %{buildroot}%{_bindir}
mkdir -p %{buildroot}%{_datadir}/turnup
mkdir -p %{buildroot}%{_datadir}/applications
mkdir -p %{buildroot}%{_datadir}/icons/hicolor/scalable/apps

install -Dpm 0755 bin/turnup %{buildroot}%{_bindir}/turnup
install -Dpm 0644 turnup_gui.py %{buildroot}%{_datadir}/turnup/turnup_gui.py
install -Dpm 0644 data/turnup.desktop %{buildroot}%{_datadir}/applications/turnup.desktop
install -Dpm 0644 data/turnup.svg \
    %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/turnup.svg

%files
%{_bindir}/turnup
%{_datadir}/turnup/
%{_datadir}/applications/turnup.desktop
%{_datadir}/icons/hicolor/scalable/apps/turnup.svg

%changelog
* Thu Jun 11 2026 Jacob Swierstra <jacobswierstra@users.noreply.github.com> - 1.0.0-1
- Initial local Fedora RPM package
