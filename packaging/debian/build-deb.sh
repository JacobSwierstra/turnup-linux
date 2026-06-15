#!/bin/sh

set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
name=turnup
version=1.1.1
package_root="$project_root/build/deb/${name}_${version}_all"
output="$project_root/${name}_${version}_all.deb"

command -v dpkg-deb >/dev/null 2>&1 || {
    echo "dpkg-deb is required to build the Debian package." >&2
    exit 1
}

rm -rf "$package_root"
mkdir -p "$package_root/DEBIAN"

DESTDIR="$package_root" PREFIX=/usr "$project_root/install.sh"

installed_size=$(du -sk "$package_root/usr" | cut -f1)
cat > "$package_root/DEBIAN/control" <<EOF
Package: $name
Version: $version
Section: sound
Priority: optional
Architecture: all
Installed-Size: $installed_size
Maintainer: Jacob Swierstra <jacobswierstra@users.noreply.github.com>
Depends: python3, python3-tk, python3-serial, python3-pil, python3-pystray, wireplumber, playerctl, pulseaudio-utils
Homepage: https://github.com/JacobSwierstra/turnup-linux
Description: Hardware controller for Linux application audio
 Turn Up maps a hardware mixer to application audio streams and controls
 volume, mute state, media playback, and controller LEDs.
EOF

rm -f "$output"
dpkg-deb --root-owner-group --build "$package_root" "$output"
printf '\nBuilt package:\n%s\n' "$output"
