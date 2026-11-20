"""Checks that the Python sandbox is really isolated. Skipped if Docker is not available."""

import os
import unittest
from unittest import mock

from tests.helpers import ROOT, load_config
from tools.sandbox import docker_available, run_python


@unittest.skipUnless(docker_available(), "Docker is not available")
class SandboxTests(unittest.TestCase):
    def setUp(self):
        self.cfg = dict(load_config()["sandbox"], timeout_seconds=10)

    def test_runs_code(self):
        self.assertEqual(run_python("print(sum(range(10)))", self.cfg), "45")

    def test_no_network(self):
        out = run_python("import socket\nsocket.create_connection(('1.1.1.1', 53), timeout=3)", self.cfg)
        self.assertIn("Error", out)

    def test_cannot_see_project_files_or_secrets(self):
        # The host's variables (like API keys) must not reach the sandbox. (The Python image
        # has a few variables of its own, such as the public GPG_KEY used to verify Python.)
        code = (f"import os\nprint(os.path.exists({str(ROOT)!r}))\n"
                "print('GEMINI_API_KEY' in os.environ, 'top-secret-value' in str(os.environ))")
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "top-secret-value"}):
            self.assertEqual(run_python(code, self.cfg), "False\nFalse False")

    def test_filesystem_is_read_only(self):
        out = run_python("open('/usr/x', 'w')", self.cfg)
        self.assertIn("Read-only file system", out)

    def test_timeout(self):
        out = run_python("while True: pass", dict(self.cfg, timeout_seconds=2))
        self.assertIn("Timed out", out)


if __name__ == "__main__":
    unittest.main()
