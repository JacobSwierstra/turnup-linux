#!/bin/sh

set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
prefix=${PREFIX:-/usr}
destdir=${DESTDIR:-}

usage() {
    cat <<EOF
Usage: ./install.sh [--prefix PATH] [--destdir PATH]

Install Turn Up using the standard Linux filesystem layout.
PREFIX defaults to /usr and DESTDIR defaults to an empty string.
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --prefix)
            [ "$#" -ge 2 ] || { usage >&2; exit 2; }
            prefix=$2
            shift 2
            ;;
        --destdir)
            [ "$#" -ge 2 ] || { usage >&2; exit 2; }
            destdir=$2
            shift 2
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            usage >&2
            exit 2
            ;;
    esac
done

bindir="$destdir$prefix/bin"
datadir="$destdir$prefix/share"

install -d "$bindir"
install -d "$datadir/turnup"
install -d "$datadir/applications"
install -d "$datadir/icons/hicolor/scalable/apps"

install -m 0755 "$project_root/bin/turnup" "$bindir/turnup"
install -m 0644 "$project_root/turnup_gui.py" "$datadir/turnup/turnup_gui.py"
install -m 0644 "$project_root/data/turnup.desktop" "$datadir/applications/turnup.desktop"
install -m 0644 "$project_root/data/turnup.svg" "$datadir/icons/hicolor/scalable/apps/turnup.svg"
install -m 0644 "$project_root/data/turnup.svg" "$datadir/icons/hicolor/scalable/apps/turnup-linux.svg"

printf 'Installed Turn Up under %s%s\n' "${destdir:-}" "$prefix"
