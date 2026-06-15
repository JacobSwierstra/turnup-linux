#!/bin/sh

set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
name=turnup
version=1.1.1
build_dir="$project_root/build/arch"
source_dir="$build_dir/$name-$version"

command -v makepkg >/dev/null 2>&1 || {
    echo "makepkg is required to build the Arch Linux package." >&2
    exit 1
}

rm -rf "$build_dir"
mkdir -p "$source_dir/bin" "$source_dir/data"

install -pm 0755 "$project_root/install.sh" "$source_dir/install.sh"
install -pm 0755 "$project_root/bin/turnup" "$source_dir/bin/turnup"
install -pm 0644 "$project_root/turnup_gui.py" "$source_dir/turnup_gui.py"
install -pm 0644 "$project_root/data/turnup.desktop" "$source_dir/data/turnup.desktop"
install -pm 0644 "$project_root/data/turnup.svg" "$source_dir/data/turnup.svg"

tar -C "$build_dir" -czf "$build_dir/$name-$version.tar.gz" "$name-$version"
install -pm 0644 "$project_root/packaging/arch/PKGBUILD" "$build_dir/PKGBUILD"

(
    cd "$build_dir"
    makepkg --clean --force
)

for package in "$build_dir"/"$name-$version"-*.pkg.tar.*; do
    install -pm 0644 "$package" "$project_root/$(basename "$package")"
done

printf '\nBuilt packages:\n'
find "$project_root" -maxdepth 1 -type f -name "$name-*.pkg.tar.*" -print
