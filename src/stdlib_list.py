"""The standard-library modules the packaged app bundles (all of them, minus
dev tools and test suites). Shared by packaging/YouDownloader.spec and the
self-test, which checks they're really in the build."""
import importlib.util
import sys

# Not needed at runtime: IDEs, demos, test suites, packaging tools.
STDLIB_SKIP = {
    "idlelib", "turtle", "turtledemo", "test", "lib2to3", "ensurepip", "venv", "pydoc_data",
    "this", "antigravity", "__phello__", "_pyrepl", "tkinter.tix", "distutils", "pydoc",
}


def stdlib_names():
    """Top-level stdlib modules importable on this platform, minus STDLIB_SKIP."""
    names = []
    for name in sorted(getattr(sys, "stdlib_module_names", ())):
        if name in STDLIB_SKIP or name.startswith("_test") or name.startswith("__"):
            continue
        try:
            if importlib.util.find_spec(name) is None:
                continue
        except (ImportError, ValueError):
            continue
        names.append(name)
    return names
