#!/usr/bin/env bash

# Get the current script directory
script_dir=$(cd -P -- "$(dirname -- "$0")" && pwd -P)

# Root of pg-browser package
root="$script_dir/.."

# Refuse to remove the current runtime when no replacement was generated.
if [ ! -d "$root/../buildroot/build/filesystem" ]; then
    printf 'Missing filesystem source directory: %s\n' "$root/../buildroot/build/filesystem" >&2
    exit 1
fi

# Clean up
rm -rf "$root/filesystem"

# Copy the filesystem folder from the buildroot package
cp -R "$root/../buildroot/build/filesystem" "$root"

# Replace the bzimage url in the index.html based on the filesystem/filesystem.json file
bzimage_bin_file=$(grep -oP '\"bzImage\"[,\d]+\"\K\w+\.bin' "$root/filesystem/filesystem.json")
sed -i -E "s/const[[:space:]]+bzimageUrl[[:space:]]*=[[:space:]]*\"\.\/filesystem\/(.*)\"/const bzimageUrl = \"\.\/filesystem\/$bzimage_bin_file\"/" "$root/index.html"