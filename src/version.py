"""App identity. `scripts/release.ps1` / `release.sh` rewrite __version__ when
you cut a release; CI checks that the git tag (vX.Y.Z) matches it."""

__version__ = "5.0.0"

APP_NAME = "YouDownloader"

# GitHub repo whose Releases the in-app updater reads (must be public).
GITHUB_REPO = "kanishkar-oss/youdownloader"
