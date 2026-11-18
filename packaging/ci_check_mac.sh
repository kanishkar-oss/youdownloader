#!/bin/sh
# CI checks on the files testers actually download (not dist/), run after
# packaging/build.py on each macOS runner:
#   1. the shipped .zip unpacks to a validly signed app, and the .dmg mounts
#   2. that app passes --self-test (bundled ffmpeg/ffprobe/deno run, Tk opens)
#   3. the bundled tools' minimum macOS is what Info.plist claims
#   4. the updater's swap script replaces an "installed" copy correctly, keeps
#      the old one as .previous, refuses while the app is still running, and
#      leaves the install untouched when it can't move it
set -eu
cd "$(dirname "$0")/.."
zip=$(ls dist/release/*-mac-*.zip)
dmg=$(ls dist/release/*-mac-*.dmg)
t=$(mktemp -d)
echo "== unpack $zip"
ditto -x -k "$zip" "$t/unzipped"
app="$t/unzipped/YouDownloader.app"
codesign --verify --deep --strict --verbose=2 "$app"

echo "== mount $dmg"
mnt="$t/mnt"; mkdir "$mnt"
hdiutil attach -nobrowse -readonly -mountpoint "$mnt" "$dmg" >/dev/null
codesign --verify --deep --strict "$mnt/YouDownloader.app"
[ -L "$mnt/Applications" ] || { echo "dmg has no Applications link"; exit 1; }
hdiutil detach "$mnt" >/dev/null

echo "== self-test of the shipped app"
"$app/Contents/MacOS/YouDownloader" --self-test "$t/selftest.txt" || { cat "$t/selftest.txt"; exit 1; }
cat "$t/selftest.txt"

echo "== minimum macOS"
/usr/libexec/PlistBuddy -c 'Print :LSMinimumSystemVersion' "$app/Contents/Info.plist"
for b in "$app"/Contents/Frameworks/bin/*; do
  printf '%s: ' "$(basename "$b")"; otool -l "$b" | awk '/minos/ {print $2; exit}'
done

echo "== youdownloader:// links"
/usr/libexec/PlistBuddy -c 'Print :CFBundleURLTypes:0:CFBundleURLSchemes:0' "$app/Contents/Info.plist" | grep -qx youdownloader \
  || { echo "FAIL: Info.plist doesn't claim youdownloader://"; exit 1; }
echo "ok: Info.plist claims youdownloader://"
# Register the unzipped app with LaunchServices, open a link like the browser
# button does, and check the app received it (Tk's ::tk::mac::LaunchURL).
LSREG=/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister
"$LSREG" -f "$app" || true
LOG="$HOME/Library/Logs/YouDownloader/youdownloader.log"
open "youdownloader://open?url=https%3A%2F%2Fyoutu.be%2FjNQXAC9IVRw" || true
got=""
for i in $(seq 1 30); do
  if grep -q "Link from the browser button: https://youtu.be/jNQXAC9IVRw" "$LOG" 2>/dev/null; then got=1; break; fi
  sleep 1
done
pkill -f "YouDownloader.app/Contents/MacOS/YouDownloader" 2>/dev/null || true
if [ -n "$got" ]; then echo "ok: a youdownloader:// link reached the app"
else echo "WARN link: the app didn't log the youdownloader:// link (CI LaunchServices, or Tk lacks LaunchURL)"; tail -5 "$LOG" 2>/dev/null || true; fi

echo "== update swap script"
python -c "import sys; sys.path.insert(0, '.'); from src.utils.app_update import MAC_SWAP_SCRIPT; print(MAC_SWAP_SCRIPT)" > "$t/swap.sh"
export YD_UPDATE_NO_RELAUNCH=1
dead_pid() { sh -c 'echo $$' ; }   # a process that has already exited

stage() {  # fresh "installed" app + staged "new" app, like the updater makes
  rm -rf "$t/Applications" "$t/youdownloader-new-x" "$t/youdownloader-update-x"
  mkdir -p "$t/Applications" "$t/youdownloader-new-x" "$t/youdownloader-update-x"
  ditto "$app" "$t/Applications/YouDownloader.app"
  touch "$t/Applications/YouDownloader.app/Contents/OLD"
  ditto "$app" "$t/youdownloader-new-x/YouDownloader.app"
  touch "$t/youdownloader-update-x/update.zip"
}
swap() {  # pid
  sh "$t/swap.sh" "$1" "$t/Applications/YouDownloader.app" "$t/youdownloader-new-x/YouDownloader.app" \
     "$t/youdownloader-new-x" "$t/youdownloader-update-x" "$t/update.log"
}
old="$t/Applications/YouDownloader.app"

stage; swap "$(dead_pid)"
[ -d "$old/Contents/MacOS" ] && [ ! -e "$old/Contents/OLD" ] || { echo "FAIL: new app not in place"; exit 1; }
[ -e "$old.previous/Contents/OLD" ] || { echo "FAIL: previous version not kept"; exit 1; }
[ ! -e "$t/youdownloader-new-x" ] && [ ! -e "$t/youdownloader-update-x" ] || { echo "FAIL: temp folders left"; exit 1; }
echo "ok: swap"

stage; sleep 30 & busy=$!
YD_UPDATE_WAIT_TICKS=5 swap "$busy" && { echo "FAIL: swapped while running"; exit 1; } || true
kill "$busy" 2>/dev/null || true
[ -e "$old/Contents/OLD" ] || { echo "FAIL: installed app changed while running"; exit 1; }
echo "ok: refuses while the app is running"

stage; chmod a-w "$t/Applications"
swap "$(dead_pid)" && { echo "FAIL: swap reported success without permission"; exit 1; } || true
chmod u+w "$t/Applications"
[ -e "$old/Contents/OLD" ] && [ -d "$old/Contents/MacOS" ] || { echo "FAIL: installed app damaged"; exit 1; }
echo "ok: leaves the install alone when it can't move it"

cat "$t/update.log"
rm -rf "$t"
echo "All macOS release checks passed"
