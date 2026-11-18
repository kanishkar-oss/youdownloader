"""FFmpeg conversion to QuickTime-compatible .mov (H.264 video + AAC audio).

Streams that are already H.264 / AAC are copied untouched (a fast, lossless
remux). Anything else (VP9/AV1 video above 1080p, Opus audio) is re-encoded,
using a hardware H.264 encoder when one works on this machine and falling back
to libx264 otherwise.
"""
import json
import os
import shutil
import subprocess
import threading
from typing import Callable, List, Optional, Tuple

from src.utils.logger import get_logger

logger = get_logger()

# Hide the console window ffmpeg would otherwise flash on Windows.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Candidate H.264 encoders, fastest first, with quality-oriented settings.
# VideoToolbox is the Mac hardware encoder (-q:v needs Apple Silicon; on Intel
# the encode fails and the next encoder, libx264, is used).
_ENCODERS = {
    "h264_nvenc": ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "19", "-b:v", "0"],
    "h264_qsv": ["-c:v", "h264_qsv", "-preset", "medium", "-global_quality", "20"],
    "h264_videotoolbox": ["-c:v", "h264_videotoolbox", "-q:v", "65", "-allow_sw", "0"],
    "libx264": ["-c:v", "libx264", "-preset", "medium", "-crf", "18"],
}

_working_encoders: Optional[List[str]] = None
_encoder_lock = threading.Lock()


class ConversionCancelled(Exception):
    """Raised when the user cancels while ffmpeg is running."""


class ConversionError(Exception):
    """Raised when ffmpeg can't produce the .mov."""


def find_ffprobe(ffmpeg: str) -> Optional[str]:
    """ffprobe normally ships next to ffmpeg."""
    from src.utils.paths import exe_name
    sibling = os.path.join(os.path.dirname(ffmpeg), exe_name("ffprobe"))
    return sibling if os.path.isfile(sibling) else shutil.which("ffprobe")


# Color transfer functions that mean the video is HDR (PQ / HLG).
_HDR_TRANSFERS = ("smpte2084", "arib-std-b67")

# HDR -> SDR (BT.709) tone mapping. Without it HDR footage converted to 8-bit
# H.264 looks grey and washed out.
_TONEMAP = ("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
            "tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p")


def probe(path: str, ffprobe: str) -> Tuple[Optional[str], Optional[str], float]:
    """Return (video codec, audio codec, duration seconds) of the first streams."""
    info = probe_details(path, ffprobe)
    return info["vcodec"], info["acodec"], info["duration"]


def probe_details(path: str, ffprobe: str) -> dict:
    """Codecs, duration, and whether the first video stream is HDR."""
    out = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries",
         "stream=codec_type,codec_name,color_transfer,pix_fmt:format=duration",
         "-of", "json", path],
        capture_output=True, text=True, creationflags=_NO_WINDOW, timeout=60,
    )
    data = json.loads(out.stdout or "{}")
    vcodec = acodec = None
    hdr = False
    pix_fmt = None
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video" and vcodec is None:
            vcodec = stream.get("codec_name")
            hdr = stream.get("color_transfer") in _HDR_TRANSFERS
            pix_fmt = stream.get("pix_fmt")
        elif stream.get("codec_type") == "audio" and acodec is None:
            acodec = stream.get("codec_name")
    try:
        duration = float(data.get("format", {}).get("duration") or 0)
    except ValueError:
        duration = 0.0
    return {"vcodec": vcodec, "acodec": acodec, "duration": duration, "hdr": hdr,
            "pix_fmt": pix_fmt}


def _detect_encoders(ffmpeg: str) -> List[str]:
    """Which H.264 encoders actually run here (a listed GPU encoder may lack hardware)."""
    global _working_encoders
    with _encoder_lock:
        if _working_encoders is None:
            working = []
            for name in _ENCODERS:
                if name == "libx264":
                    continue
                try:
                    r = subprocess.run(
                        [ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                         "-i", "testsrc2=size=1280x720:rate=30", "-t", "0.2",
                         "-c:v", name, "-f", "null", "-"],
                        capture_output=True, creationflags=_NO_WINDOW, timeout=20,
                    )
                    if r.returncode == 0:
                        working.append(name)
                except (OSError, subprocess.SubprocessError):
                    pass
            working.append("libx264")
            _working_encoders = working
            logger.info(f"H.264 encoders available: {', '.join(working)}")
        return list(_working_encoders)


def to_quicktime_mov(
    src: str,
    ffmpeg: str,
    is_cancelled: Callable[[], bool] = lambda: False,
    on_progress: Optional[Callable[[float, str], None]] = None,
) -> str:
    """
    Convert `src` into `<same name>.mov` with H.264 + AAC, deleting `src` on success.

    Returns the .mov path. Raises ConversionCancelled / ConversionError.
    """
    ffprobe = find_ffprobe(ffmpeg)
    if not ffprobe:
        raise ConversionError("ffprobe was not found next to FFmpeg")

    details = probe_details(src, ffprobe)
    vcodec, acodec, duration, hdr = (details["vcodec"], details["acodec"],
                                     details["duration"], details["hdr"])
    base, _ = os.path.splitext(src)
    dst = base + ".mov"
    tmp = base + ".converting.mov"

    # Only 8-bit 4:2:0 H.264 is safe to copy; QuickTime rejects High10 / 4:4:4.
    copy_video = vcodec is None or (
        vcodec == "h264" and not hdr and details["pix_fmt"] in (None, "yuv420p", "yuvj420p"))
    copy_audio = acodec in (None, "aac")
    audio_args = ["-c:a", "copy"] if copy_audio else ["-c:a", "aac", "-b:a", "256k"]

    encoders = [None] if copy_video else _detect_encoders(ffmpeg)
    last_error = ""
    for encoder in encoders:
        if encoder is None:
            video_args, action = ["-c:v", "copy"], "Packaging MOV"
        else:
            # yuv420p: 10-bit/HDR sources would otherwise yield High10 H.264,
            # which QuickTime refuses to play.
            video_args = _ENCODERS[encoder] + ["-pix_fmt", "yuv420p", "-tag:v", "avc1"]
            if hdr:
                video_args = ["-vf", _TONEMAP] + video_args
            action = f"Converting to H.264 ({encoder.replace('h264_', '').upper()})"
            if hdr:
                action += ", HDR to SDR"
        logger.info(f"MOV: {os.path.basename(src)} video={vcodec}{' HDR' if hdr else ''} "
                    f"audio={acodec} -> {action}")

        cmd = [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-nostats",
            "-progress", "pipe:1", "-i", src,
            "-map", "0:v:0?", "-map", "0:a:0?",
            *video_args, *audio_args,
            "-movflags", "+faststart", tmp,
        ]
        ok, last_error = _run_ffmpeg(cmd, duration, action, is_cancelled, on_progress)
        if ok:
            os.replace(tmp, dst)
            if os.path.abspath(src) != os.path.abspath(dst):
                try:
                    os.remove(src)
                except OSError as e:
                    logger.warning(f"Could not remove intermediate file {src}: {e}")
            return dst
        _remove(tmp)
        if is_cancelled():
            raise ConversionCancelled()
        logger.warning(f"MOV conversion with {encoder or 'stream copy'} failed: {last_error}")

    raise ConversionError(f"Could not convert to MOV: {last_error or 'ffmpeg failed'}")


def _run_ffmpeg(cmd, duration, action, is_cancelled, on_progress) -> Tuple[bool, str]:
    """Run ffmpeg, streaming -progress output; kill it if the user cancels."""
    stderr_lines: List[str] = []
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
        text=True, encoding="utf-8", errors="replace", creationflags=_NO_WINDOW,
    )
    # Drain stderr on a side thread so a chatty ffmpeg can't fill the pipe and stall.
    drain = threading.Thread(target=lambda: stderr_lines.extend(proc.stderr), daemon=True)
    drain.start()
    if on_progress:
        on_progress(0.0, action)
    try:
        for line in proc.stdout:
            if is_cancelled():
                proc.kill()
                break
            key, _, value = line.strip().partition("=")
            if key == "out_time_us" and on_progress and duration > 0:
                try:
                    on_progress(min(1.0, int(value) / 1_000_000 / duration), action)
                except ValueError:
                    pass
        proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    drain.join(timeout=5)
    return proc.returncode == 0 and not is_cancelled(), "".join(stderr_lines).strip()[-500:]


def _remove(path: str) -> None:
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass
