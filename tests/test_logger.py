"""Tests that the logger doesn't stack handlers or propagate to root."""
import os
import tempfile
import sys
import importlib
import unittest
# Keep test runs out of the real logs/youdownloader.log.
os.environ.setdefault("YOUDOWNLOADER_LOG_DIR", os.path.join(tempfile.gettempdir(), "youdownloader-test-logs"))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestLogger(unittest.TestCase):
    def test_no_handler_duplication_on_reimport(self):
        import src.utils.logger as logmod
        importlib.reload(logmod)
        n1 = len(logmod.get_logger().handlers)
        importlib.reload(logmod)
        n2 = len(logmod.get_logger().handlers)
        self.assertEqual(n1, n2)
        self.assertGreaterEqual(n1, 1)

    def test_does_not_propagate(self):
        import src.utils.logger as logmod
        self.assertFalse(logmod.get_logger().propagate)


if __name__ == "__main__":
    unittest.main()
