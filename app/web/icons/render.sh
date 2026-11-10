#!/usr/bin/env bash
# Renders the raster icons in icons/generated/ from mark.svg and favicon.svg; commit the output.
# Needs rsvg-convert (librsvg2-tools) and ImageMagick's convert. Usage: bash icons/render.sh, from app/web.
# discord/discord-avatar-idle.gif, her Discord avatar, is not made here and not bundled: it is AshleyMark's idle animation
# retimed to a 6 s loop and captured frame by frame in a headless browser, so re-render it by hand when the mark changes.
set -euo pipefail
cd "$(dirname "$0")"
out=generated
mkdir -p "$out"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

# The maskable icon keeps the mark inside the central 80% circle a launcher may crop to.
grep -c 'id="mark" transform="scale(1)"' mark.svg >/dev/null
sed 's/id="mark" transform="scale(1)"/id="mark" transform="scale(.8)"/' mark.svg > "$work/maskable.svg"

png() { rsvg-convert -w "$2" -h "$2" "$1" -o "$3"; }
png mark.svg 1024 "$out/discord-avatar.png"
png mark.svg 512 "$out/icon-512.png"
png mark.svg 192 "$out/icon-192.png"
png mark.svg 180 "$out/apple-touch-icon.png"
png "$work/maskable.svg" 512 "$out/icon-maskable-512.png"
png favicon.svg 32 "$work/favicon-32.png"
convert "$work/favicon-32.png" "$out/favicon.ico"
ls -l "$out"
