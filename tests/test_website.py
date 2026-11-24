"""Phase 3: the public website (read-only, escaped, verifiable) and the owner dashboard."""

import hashlib
import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import dashboard
from core import integrity, killswitch
from knowledge.db import KnowledgeBase
from tests.helpers import load_config, mock_runner, temp_dir
from website import build, pages
from website import verify_chain


def built_site(extra_finding: dict | None = None):
    """Run three mock cycles (plus an optional extra finding) and build the site."""
    data = temp_dir()
    runner = mock_runner(data)
    for _ in range(3):
        runner.run_cycle()
    if extra_finding:
        runner.kb.add_finding(**extra_finding)
    out = temp_dir() / "docs"
    build.build(data, out, load_config())
    return data, out


class WebsiteTests(unittest.TestCase):
    def test_site_has_every_page_and_open_data(self):
        _, out = built_site()
        for name in ("index.html", "roadmap.html", "findings.html", "path.html", "rules.html",
                     "proposals.html", "verify.html", "style.css", "verify_chain.py",
                     "findings/F0001.html", "cycles/0001.html", "cycles/0001-transcript.html",
                     "data/cycles.json", "data/findings.json", ".nojekyll"):
            self.assertTrue((out / name).exists(), name)
        self.assertIn("Version: 2", (out / "rules.html").read_text(encoding="utf-8"))

    def test_building_never_changes_the_data(self):
        data = temp_dir()
        runner = mock_runner(data)
        runner.run_cycle()
        before = hashlib.sha256((data / "knowledge.db").read_bytes()).hexdigest()
        build.build(data, temp_dir() / "docs", load_config())
        after = hashlib.sha256((data / "knowledge.db").read_bytes()).hexdigest()
        self.assertEqual(before, after)

    def test_agent_text_is_escaped_and_only_web_links_are_clickable(self):
        evil = {"cycle": 1, "task_id": None, "statement": "<script>alert(1)</script>",
                "type": "verifiable", "confidence": 0.5, "refutation_condition": "<img src=x>",
                "evidence": "e", "status": "proposed",
                "sources": ["javascript:alert(1)", "https://example.org/paper"],
                "builds_on": [], "created_by": "a", "reviewed_by": None, "review_note": None}
        _, out = built_site(evil)
        fid = json.loads((out / "data" / "findings.json").read_text(encoding="utf-8"))[-1]["id"]
        page = (out / "findings" / f"{fid}.html").read_text(encoding="utf-8")
        self.assertNotIn("<script>alert", page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)
        self.assertNotIn("<img src=x>", page)
        self.assertNotIn('href="javascript:', page)
        self.assertIn('href="https://example.org/paper"', page)
        self.assertNotIn("<script>alert", (out / "findings.html").read_text(encoding="utf-8"))

    def test_published_chain_can_be_checked_by_anyone(self):
        _, out = built_site()
        cycles_file = out / "data" / "cycles.json"
        with mock.patch("builtins.print"):
            self.assertEqual(verify_chain.main(str(cycles_file)), 0)
        cycles = json.loads(cycles_file.read_text(encoding="utf-8"))
        self.assertEqual(verify_chain.chain_hash("x", cycles[0]["log"]),
                         integrity.chain_hash("x", cycles[0]["log"]))   # same rule as the core
        cycles[1]["log"]["outcome"] = "rewritten"
        cycles_file.write_text(json.dumps(cycles), encoding="utf-8")
        with mock.patch("builtins.print"):
            self.assertEqual(verify_chain.main(str(cycles_file)), 1)

    def test_builder_never_replaces_a_folder_it_did_not_make(self):
        out = temp_dir() / "docs"
        out.mkdir()
        (out / "important.txt").write_text("keep me", encoding="utf-8")
        with self.assertRaises(SystemExit):
            build.prepare_output(out)
        self.assertTrue((out / "important.txt").exists())

    def test_markdown_for_owner_documents_is_escaped(self):
        result = pages.markdown("# Title\n\n<b>raw</b> and **bold**\n- item")
        self.assertIn("&lt;b&gt;raw&lt;/b&gt;", result)
        self.assertIn("<strong>bold</strong>", result)
        self.assertIn("<li>item</li>", result)


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), dashboard.Handler)
        self.port = self.server.server_address[1]
        self.patch_port = mock.patch.object(dashboard, "PORT", self.port)
        self.patch_port.start()
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.stop_file = temp_dir() / "STOP"
        self.patch_stop = mock.patch.object(killswitch, "STOP_FILE", self.stop_file)
        self.patch_stop.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.patch_port.stop()
        self.patch_stop.stop()

    def post(self, data: dict, host: str | None = None):
        body = "&".join(f"{k}={v}" for k, v in data.items()).encode()
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}/action", data=body,
                                         headers={"Host": host or f"127.0.0.1:{self.port}"})
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as e:
            return e.code, None

    def test_actions_need_the_secret_token(self):
        self.assertEqual(self.post({"action": "stop"})[0], 403)
        self.assertEqual(self.post({"action": "stop", "token": "wrong"})[0], 403)
        self.assertFalse(self.stop_file.exists())

    def test_other_host_names_are_refused(self):
        status, _ = self.post({"action": "stop", "token": dashboard.TOKEN}, host="evil.example")
        self.assertEqual(status, 403)

    def test_stop_and_allow_buttons(self):
        status, reply = self.post({"action": "stop", "token": dashboard.TOKEN})
        self.assertEqual(status, 200)
        self.assertTrue(self.stop_file.exists())
        self.post({"action": "allow", "token": dashboard.TOKEN})
        self.assertFalse(self.stop_file.exists())

    def test_approve_with_nothing_changed_does_nothing(self):
        before = (integrity.CORE_DIR / "manifest.json").read_text(encoding="utf-8")
        _, reply = self.post({"action": "approve", "token": dashboard.TOKEN,
                              "reason": "x", "confirm": "yes"})
        self.assertIn("Nothing to approve", reply["message"])
        self.assertEqual(before, (integrity.CORE_DIR / "manifest.json").read_text(encoding="utf-8"))

    def test_site_files_only_from_the_site_folder(self):
        with mock.patch.object(dashboard, "site_dir", return_value=temp_dir()):
            request = urllib.request.Request(f"http://127.0.0.1:{self.port}/site/../.env",
                                             headers={"Host": f"127.0.0.1:{self.port}"})
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(request)
            self.assertEqual(caught.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
