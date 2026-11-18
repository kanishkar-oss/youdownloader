#!/bin/sh
# Publish a new YouDownloader version (macOS / Linux equivalent of release.ps1).
#
#   ./scripts/release.sh 5.0.1 "Fixes playlist names on Mac"
#   ./scripts/release.sh 5.1.0          # notes = commit messages since the last release
#
# Bumps src/version.py, commits, tags vX.Y.Z (the tag message becomes the
# release notes) and pushes; GitHub Actions builds and publishes the release.
set -eu
cd "$(dirname "$0")/.."

version="${1:-}"; notes="${2:-}"
echo "$version" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$' || { echo "usage: $0 X.Y.Z [notes]"; exit 1; }
tag="v$version"
[ "$(git rev-parse --abbrev-ref HEAD)" = "main" ] || { echo "Releases are cut from main."; exit 1; }
[ -z "$(git tag -l "$tag")" ] || { echo "Tag $tag already exists."; exit 1; }
current=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' src/version.py)
newest=$(printf '%s\n%s\n' "$current" "$version" | sort -t. -k1,1n -k2,2n -k3,3n | tail -1)
if [ "$version" = "$current" ] || [ "$newest" != "$version" ]; then
  echo "$version isn't newer than the current $current. Installed apps only update to a higher version."; exit 1
fi
git fetch origin main --quiet
[ "$(git rev-list --count HEAD..origin/main)" = "0" ] || { echo "origin/main is ahead of you. Pull first."; exit 1; }

if [ -n "$(git status --porcelain)" ]; then
  git status --short
  printf "Include these in the release commit? [y/N] "; read -r answer
  case "$answer" in y|Y) ;; *) echo "Commit or stash them first."; exit 1;; esac
fi

if [ -z "$notes" ]; then
  last=$(git describe --tags --abbrev=0 2>/dev/null || true)
  range=${last:+$last..}HEAD
  notes=$(git log "$range" --no-merges --pretty='- %s' | grep -v '^- Release v' || true)
  [ -n "$notes" ] || notes="- Improvements and fixes"
fi

sed -i.bak "s/__version__ = \".*\"/__version__ = \"$version\"/" src/version.py && rm -f src/version.py.bak
printf "\nRelease notes:\n%s\n\n" "$notes"
git add -A
git commit -m "Release $tag" --quiet
git tag -a "$tag" --cleanup=verbatim -m "$notes"
git push origin main
git push origin "$tag"

repo=$(sed -n 's/^GITHUB_REPO = "\(.*\)"/\1/p' src/version.py)
echo "Pushed $tag. Builds take ~15 minutes: https://github.com/$repo/actions"
