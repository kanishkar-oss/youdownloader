"""Double-click launcher for YouDownloader (no console window).

.pyw files open with pythonw. If that's the system Python rather than this
project's .venv (which has the dependencies), relaunch with the venv's pythonw.
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
VENV_PYTHONW = os.path.join(ROOT, ".venv", "Scripts", "pythonw.exe")

if os.path.isfile(VENV_PYTHONW) and \
        os.path.normcase(os.path.abspath(sys.prefix)) != os.path.normcase(os.path.join(ROOT, ".venv")):
    subprocess.Popen([VENV_PYTHONW, os.path.abspath(__file__)], cwd=ROOT)
    sys.exit(0)

sys.path.insert(0, ROOT)
from main import main  # noqa: E402

sys.exit(main())
