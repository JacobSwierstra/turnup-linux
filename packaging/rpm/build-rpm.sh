#!/bin/sh

set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
name=turnup
version=1.0.0
topdir="$project_root/build/rpmbuild"
source_dir="$topdir/SOURCES/$name-$version"

rm -rf "$source_dir"
mkdir -p "$topdir/BUILD" "$topdir/BUILDROOT" "$topdir/RPMS" "$topdir/SOURCES" "$topdir/SPECS" "$topdir/SRPMS"
mkdir -p "$source_dir/bin" "$source_dir/data"

install -pm 0755 "$project_root/install.sh" "$source_dir/install.sh"
install -pm 0644 "$project_root/turnup_gui.py" "$source_dir/turnup_gui.py"
install -pm 0755 "$project_root/bin/turnup" "$source_dir/bin/turnup"
install -pm 0644 "$project_root/data/turnup.desktop" "$source_dir/data/turnup.desktop"
install -pm 0644 "$project_root/data/turnup.svg" "$source_dir/data/turnup.svg"

tar -C "$topdir/SOURCES" -czf "$topdir/SOURCES/$name-$version.tar.gz" "$name-$version"
install -pm 0644 "$project_root/packaging/rpm/turnup.spec" "$topdir/SPECS/turnup.spec"

rpmbuild -ba --define "_topdir $topdir" "$topdir/SPECS/turnup.spec"

for rpm in "$topdir"/RPMS/*/"$name"-"$version"-*.rpm; do
    install -pm 0644 "$rpm" "$project_root/$(basename "$rpm")"
done
for srpm in "$topdir"/SRPMS/"$name"-"$version"-*.src.rpm; do
    install -pm 0644 "$srpm" "$project_root/$(basename "$srpm")"
done

printf '\nBuilt packages:\n'
find "$project_root" -maxdepth 1 -type f -name "$name-*.rpm" -print
