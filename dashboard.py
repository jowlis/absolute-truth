"""Your owner dashboard: a page in your browser, reachable only from your own computer.

  Double-click Dashboard.bat   (or: py dashboard.py, or py dashboard.py --mock)

Buttons start the same commands you could type (run.py, website/build.py) and show their
output live. It can create or remove the STOP file and approve core changes (like
lock_core.py). It never writes findings: only runs, through core/recorder.py, do that.

Safety: it listens on 127.0.0.1 only (no other computer can reach it), checks the
address the browser used (against DNS tricks), and every action needs a secret token
that only this page knows, so other websites can't press its buttons.
"""

import argparse
import json
import os
import secrets
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import tomllib

import lock_core
from core import integrity, killswitch

ROOT = Path(__file__).resolve().parent
_CONFIG = tomllib.loads((ROOT / "config.toml").read_text(encoding="utf-8"))
REPO_URL = _CONFIG.get("site", {}).get("repo_url", "https://github.com")
PRIVATE_REPO = _CONFIG.get("private", {}).get("repo", "")
HOST, PORT = "127.0.0.1", 8765
TOKEN = secrets.token_urlsafe(24)
MOCK = False                       # set by --mock: use data-mock/ and docs-mock/


def runs_in_cloud() -> bool:
    """True when real runs happen on GitHub (see [cloud] in config.toml); mock runs are local."""
    config = tomllib.loads((ROOT / "config.toml").read_text(encoding="utf-8"))
    return bool(config.get("cloud", {}).get("runs_in_cloud")) and not MOCK


def site_dir() -> Path:
    return ROOT / ("docs-mock" if MOCK else "docs")


def with_mock(args: list) -> list:
    return args + (["--mock"] if MOCK else [])


# ---- one background job at a time (a run, a verify, a website build) ----------------

class Job:
    def __init__(self):
        self.lock = threading.Lock()
        self.title, self.lines, self.running, self.exit_code = "", [], False, None

    def start(self, title: str, commands: list) -> bool:
        """Run commands one after another in the background. False if a job is running."""
        with self.lock:
            if self.running:
                return False
            self.title, self.lines, self.running, self.exit_code = title, [], True, None
        threading.Thread(target=self._run, args=(commands,), daemon=True).start()
        return True

    def _run(self, commands: list) -> None:
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        code = 0
        for args in commands:
            self.lines.append(f"$ py {' '.join(args)}")
            process = subprocess.Popen([sys.executable, "-u", *args], cwd=ROOT, env=env,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, encoding="utf-8", errors="replace")
            for line in process.stdout:
                self.lines.append(line.rstrip("\n"))
            code = process.wait()
            if code != 0:
                break
        self.exit_code, self.running = code, False

    def snapshot(self) -> dict:
        return {"title": self.title, "running": self.running, "exit_code": self.exit_code,
                "output": "\n".join(self.lines[-400:])}


JOB = Job()


def state() -> dict:
    return {"job": JOB.snapshot(), "stopped": killswitch.STOP_FILE.exists(),
            "core_problems": integrity.check_core(), "rules": integrity.rules_in_force(),
            "site_built": (site_dir() / "index.html").exists(), "mock": MOCK,
            "cloud": runs_in_cloud()}


def act(form: dict) -> str:
    """Carry out one button press. Returns a message for the page."""
    action = form.get("action", "")
    if action == "run":
        if runs_in_cloud():
            return "Runs happen in the cloud: start one on GitHub (Actions, Run workflow)."
        if integrity.check_core():
            return "Not started: the core has unapproved changes (see Approve core changes)."
        cycles = max(1, min(5, int(form.get("cycles", "1") or 1)))
        team = "resource" if form.get("team") == "resource" else "truth"
        started = JOB.start(f"Running {cycles} {team} cycle(s), then building the website",
                            [with_mock(["run.py", "--team", team, "--cycles", str(cycles)]),
                             with_mock(["website/build.py"])])
        return "Started." if started else "Something is already running."
    if action == "stop":
        killswitch.STOP_FILE.touch()
        return "STOP is set: the run halts before its next API call or tool call."
    if action == "allow":
        killswitch.STOP_FILE.unlink(missing_ok=True)
        return "Runs are allowed again."
    if action == "verify":
        return ("Checking..." if JOB.start("Verify", [with_mock(["run.py", "--verify"])])
                else "Something is already running.")
    if action == "build":
        return ("Building..." if JOB.start("Build the website", [with_mock(["website/build.py"])])
                else "Something is already running.")
    if action == "approve":
        problems = integrity.check_core()
        if not problems:
            return "The core is unchanged since it was last approved. Nothing to approve."
        problem = lock_core.version_problem(problems)
        if problem:
            return problem
        reason = form.get("reason", "").strip()
        if not reason or form.get("confirm", "").strip().lower() != "yes":
            return "Not approved: give a reason and type yes to confirm."
        if JOB.running:
            return "Wait until the current job has finished."
        fingerprint = integrity.lock(reason)
        return (f"Approved. New core fingerprint {fingerprint}. Now commit core/ in GitHub "
                "Desktop (Commit, then Push).")
    return "Unknown action."


# ---- the web server ------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):          # keep the console quiet
        pass

    def _allowed_host(self) -> bool:
        return self.headers.get("Host", "") in (f"127.0.0.1:{PORT}", f"localhost:{PORT}")

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self._allowed_host():
            return self._send(403, b"Forbidden", "text/plain")
        url = urlparse(self.path)
        if url.path == "/":
            return self._send(200, control_page().encode("utf-8"), "text/html; charset=utf-8")
        if url.path == "/style.css":
            return self._send(200, (ROOT / "website" / "style.css").read_bytes(), "text/css")
        if url.path == "/state":
            token = parse_qs(url.query).get("token", [""])[0]
            if not secrets.compare_digest(token, TOKEN):
                return self._send(403, b"Forbidden", "text/plain")
            return self._send(200, json.dumps(state()).encode("utf-8"), "application/json")
        if url.path.startswith("/site/"):
            return self._serve_site(url.path[len("/site/"):] or "index.html")
        return self._send(404, b"Not found", "text/plain")

    def _serve_site(self, relative: str):
        base = site_dir().resolve()
        target = (base / relative).resolve()
        if target.is_dir():
            target = target / "index.html"
        if base not in target.parents or not target.is_file():
            return self._send(404, b"Not found (build the website first)", "text/plain")
        types = {".html": "text/html; charset=utf-8", ".css": "text/css",
                 ".json": "application/json", ".py": "text/plain; charset=utf-8"}
        return self._send(200, target.read_bytes(), types.get(target.suffix, "application/octet-stream"))

    def do_POST(self):
        if not self._allowed_host() or urlparse(self.path).path != "/action":
            return self._send(403, b"Forbidden", "text/plain")
        length = min(int(self.headers.get("Content-Length", 0) or 0), 10_000)
        form = {k: v[0] for k, v in parse_qs(self.rfile.read(length).decode("utf-8")).items()}
        if not secrets.compare_digest(form.get("token", ""), TOKEN):
            return self._send(403, b"Forbidden", "text/plain")
        try:
            message = act(form)
        except Exception as e:     # show the problem on the page instead of failing silently
            message = f"Error: {type(e).__name__}: {e}"
        return self._send(200, json.dumps({"message": message}).encode("utf-8"), "application/json")


def esc(text: str) -> str:
    import html
    return html.escape(str(text), quote=True)


def control_page() -> str:
    mock_note = ('<p class="badge contested">MOCK MODE: pretend models, data-mock/</p>'
                 if MOCK else "")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Owner dashboard · Absolute Truth</title>
<link rel="stylesheet" href="/style.css"></head>
<body>
<header><span class="title">Owner dashboard</span>
<p class="tagline">Only reachable from this computer. Keep the Dashboard window open while you use it.</p>
<nav><a href="/site/index.html" target="_blank">Open the website preview</a>
<a href="/site/path.html" target="_blank">The path</a>
<a href="/site/findings.html" target="_blank">Findings</a>
<a href="/site/updates.html" target="_blank">Updates</a>
<a href="https://github.com/{esc(PRIVATE_REPO)}" target="_blank">Private: proposals and inbox</a></nav></header>
<main>
{mock_note}
<h2>Status</h2>
<div class="card"><dl class="facts">
<dt>Core</dt><dd id="core">…</dd>
<dt>Kill switch</dt><dd id="stop">…</dd>
<dt>Current job</dt><dd id="job">…</dd>
</dl></div>

<h2>Run</h2>
<p id="cloud-note" class="card" hidden>Runs happen automatically in the cloud every day.
To start one now: open <a href="{esc(REPO_URL)}/actions" target="_blank">GitHub Actions</a>,
choose <em>Truth team</em> or <em>Resource team</em>, then <em>Run workflow</em>. To pause
everything: add a file named <code>STOP</code> to the repository on GitHub (Add file, Create
new file), or disable the workflows there. Use GitHub Desktop's Pull to bring the latest
data to this computer.</p>
<div class="filters" id="run-controls">
<label>Team <select id="team"><option value="truth">truth team</option>
<option value="resource">resource team</option></select></label>
<label>Cycles <select id="cycles"><option>1</option><option>2</option><option selected>3</option>
<option>4</option><option>5</option></select></label>
<button class="primary" data-action="run">Run</button>
<button data-action="stop">Stop</button>
<button data-action="allow">Allow runs again</button>
<button data-action="verify">Verify</button>
<button data-action="build">Build website</button>
</div>
<p id="message" class="muted"></p>
<pre id="output" style="max-height: 420px; overflow: auto">No job yet.</pre>

<h2>Publish the website</h2>
<p>After a run, the website is rebuilt automatically in the <code>docs</code> folder. To publish
it: in GitHub Desktop, tick the changed files, write a short summary (for example "Cycles 15-17"),
click <strong>Commit to main</strong>, then <strong>Push origin</strong>. GitHub Pages updates
the public site within a few minutes.</p>

<h2>Approve core changes</h2>
<div class="card">
<p id="core-detail" class="muted">…</p>
<div class="filters">
<label>Reason <input id="reason" size="40" placeholder="why the change was made"></label>
<label>Type yes <input id="confirm" size="5"></label>
<button data-action="approve">Approve</button>
</div>
</div>
</main>
<script>
const TOKEN = {json.dumps(TOKEN)};
const $ = id => document.getElementById(id);
async function refresh() {{
  const r = await fetch("/state?token=" + encodeURIComponent(TOKEN));
  const s = await r.json();
  const core = s.core_problems;
  $("core").innerHTML = core.length
    ? '<span class="bad">changed without approval</span>'
    : '<span class="ok">locked and intact</span> · constitution v' + s.rules.constitution_version;
  $("core-detail").textContent = core.length ? "Changes: " + core.join("; ")
    : "Nothing to approve: the core is exactly as you last approved it.";
  $("stop").innerHTML = s.stopped ? '<span class="bad">STOP is set: runs halt</span>'
                                  : '<span class="ok">runs allowed</span>';
  const j = s.job;
  $("job").textContent = !j.title ? "none" : j.title + (j.running ? " (running…)"
                          : j.exit_code === 0 ? " (finished)" : " (stopped with problems)");
  const out = $("output"), atBottom = out.scrollTop + out.clientHeight >= out.scrollHeight - 30;
  out.textContent = j.output || "No job yet.";
  if (atBottom) out.scrollTop = out.scrollHeight;
  for (const b of document.querySelectorAll("button[data-action=run], button[data-action=verify], button[data-action=build]"))
    b.disabled = j.running;
  $("cloud-note").hidden = !s.cloud;
  for (const el of document.querySelectorAll("#run-controls select, button[data-action=run]"))
    el.disabled = el.disabled || s.cloud;
}}
for (const b of document.querySelectorAll("button[data-action]")) {{
  b.onclick = async () => {{
    const body = new URLSearchParams({{token: TOKEN, action: b.dataset.action,
      cycles: $("cycles").value, team: $("team").value, reason: $("reason").value,
      confirm: $("confirm").value}});
    const r = await fetch("/action", {{method: "POST", body}});
    $("message").textContent = (await r.json()).message;
    refresh();
  }};
}}
refresh();
setInterval(refresh, 2000);
</script>
</body></html>"""


def main() -> int:
    global MOCK
    parser = argparse.ArgumentParser(description="Open the owner dashboard in your browser.")
    parser.add_argument("--mock", action="store_true", help="use pretend models and data-mock/")
    parser.add_argument("--no-browser", action="store_true", help="don't open a browser")
    args = parser.parse_args()
    MOCK = args.mock
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    url = f"http://127.0.0.1:{PORT}/"
    print(f"Owner dashboard running at {url}")
    print("Keep this window open while you use it. Close it (or press Ctrl+C) to stop the dashboard.")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
