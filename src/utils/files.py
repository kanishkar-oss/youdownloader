"""Renaming downloaded files safely."""
import os
from typing import List, Optional, Tuple

from src.utils.validators import validate_filename


def _same_file(a: str, b: str) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return os.path.normcase(a) == os.path.normcase(b)


def rename_download(path: str, new_name: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Rename `path` to `new_name` (keeping its extension and folder). Sidecar files
    sharing the old name (e.g. "Old.en.srt") are renamed with it.

    Returns (new_path, None) or (None, error message).
    """
    if not path or not os.path.isfile(path):
        return None, "The file no longer exists (it may have been moved or deleted)"
    folder, filename = os.path.split(path)
    stem, ext = os.path.splitext(filename)
    clean, error = validate_filename(new_name, ext)
    if error:
        return None, error
    if clean == stem:
        return path, None

    moves: List[Tuple[str, str]] = [(path, os.path.join(folder, clean + ext))]
    for other in os.listdir(folder):
        if other != filename and other.startswith(stem + ".") and not other.endswith(ext):
            moves.append((os.path.join(folder, other), os.path.join(folder, clean + other[len(stem):])))

    for src, dst in moves:
        # Case-only renames ("song" -> "Song") are fine: on case-insensitive
        # disks (Windows, default macOS APFS) dst "exists" but is the same file.
        if os.path.exists(dst) and not _same_file(src, dst):
            return None, f"“{os.path.basename(dst)}” already exists in that folder"
    done: List[Tuple[str, str]] = []
    try:
        for src, dst in moves:
            os.rename(src, dst)
            done.append((src, dst))
    except OSError as e:
        for src, dst in reversed(done):  # undo a partial rename
            try:
                os.rename(dst, src)
            except OSError:
                pass
        return None, f"Couldn't rename: {e.strerror or e}"
    return moves[0][1], None
