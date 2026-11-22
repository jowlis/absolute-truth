"""Sandboxed Python executor.

Each run starts a fresh, throwaway Docker container that has:
  - no network (--network none),
  - a read-only filesystem, apart from a small temporary /tmp,
  - no mounted folders: it cannot see your files, the knowledge base, config or core/,
  - no environment variables from your machine: it cannot see your API keys,
  - no root user and no extra privileges,
  - limits on memory, CPU, number of processes and run time.

If Docker is not available, code is NOT run anywhere else. The agent is told the
sandbox is unavailable instead.
"""

import shutil
import subprocess
import uuid
from pathlib import Path


def docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(["docker", "info"], capture_output=True, timeout=15)
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def ensure_image(cfg: dict, say=print) -> bool:
    """Make sure the sandbox image exists; build it from sandbox/Dockerfile if not.

    Building needs the internet once (to download Python libraries). The sandbox itself
    never has network access.
    """
    image = cfg["image"]
    if subprocess.run(["docker", "image", "inspect", image], capture_output=True).returncode == 0:
        return True
    dockerfile_dir = Path(__file__).resolve().parent.parent / "sandbox"
    say(f"Building the sandbox image '{image}' (one time, about 1-3 minutes)...")
    result = subprocess.run(["docker", "build", "-t", image, str(dockerfile_dir)],
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        say("Building the sandbox image failed:\n" + result.stderr[-1500:])
        return False
    return True


def run_python(code: str, cfg: dict) -> str:
    """Run `code` in the sandbox and return its output (stdout + stderr, truncated)."""
    timeout = int(cfg["timeout_seconds"])
    name = f"sandbox-{uuid.uuid4().hex[:12]}"
    command = [
        "docker", "run", "--rm", "-i", "--name", name,
        "--network", "none",
        "--read-only", "--tmpfs", "/tmp:size=64m",
        "--memory", cfg["memory"], "--cpus", "1", "--pids-limit", "64",
        "--user", "65534:65534",            # the unprivileged "nobody" user
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--workdir", "/tmp",
        cfg["image"],
        "timeout", str(timeout), "python", "-I", "-",
    ]
    try:
        result = subprocess.run(command, input=code, capture_output=True, text=True,
                                encoding="utf-8", errors="replace",
                                timeout=timeout + 15)
    except subprocess.TimeoutExpired:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        return f"[sandbox] Timed out after {timeout} seconds."

    output = (result.stdout or "") + (("\n[stderr]\n" + result.stderr) if result.stderr else "")
    if result.returncode == 124:
        output += f"\n[sandbox] Timed out after {timeout} seconds."
    elif result.returncode != 0:
        output += f"\n[sandbox] Exit code {result.returncode}."
    limit = int(cfg["max_output_chars"])
    if len(output) > limit:
        output = output[:limit] + f"\n[sandbox] Output truncated to {limit} characters."
    return output.strip() or "[sandbox] (no output)"
