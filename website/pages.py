"""The pages of the public website, as plain Python functions that return HTML.

Everything the agents wrote is untrusted text: it is always escaped with esc(), so no
agent reply can put HTML or scripts on the site. Only plain http(s) addresses become links.
These functions only format data they are given; they never read or change the data.
"""

import html
import json
import re

STATUS_LABELS = {
    "supported": "supported", "conceptual": "conceptual", "contested": "contested",
    "refuted": "refuted", "superseded": "superseded", "proposed": "unreviewed",
}
ROADMAP_MARKS = {"proposed": "○", "active": "▶", "done": "✓", "abandoned": "✗"}


# ---- small helpers -------------------------------------------------------------

def esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def link_or_text(value) -> str:
    text = str(value or "").strip()
    if re.fullmatch(r"https?://[^\s<>\"'`]+", text):
        return f'<a href="{esc(text)}" rel="nofollow noopener noreferrer">{esc(text)}</a>'
    return esc(text)


def badge(status: str) -> str:
    return f'<span class="badge {esc(status)}">{esc(STATUS_LABELS.get(status, status))}</span>'


def finding_link(fid: str, prefix: str) -> str:
    return f'<a href="{prefix}findings/{esc(fid)}.html">{esc(fid)}</a>'


def cycle_link(number: int, prefix: str, text: str | None = None) -> str:
    return f'<a href="{prefix}cycles/{int(number):04d}.html">{esc(text or f"Cycle {number}")}</a>'


def bullets(items, empty="none") -> str:
    items = [i for i in items or [] if str(i).strip()]
    if not items:
        return f'<p class="muted">{esc(empty)}</p>'
    return "<ul>" + "".join(f'<li class="text">{esc(i)}</li>' for i in items) + "</ul>"


def markdown(text: str) -> str:
    """A very small Markdown reader for the owner's own documents (constitution, changelog):
    headings, lists, paragraphs, **bold** and `code`. Text is escaped first."""
    out, paragraph, in_list = [], [], False

    def inline(s: str) -> str:
        s = esc(s)
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        return re.sub(r"`([^`]+)`", r"<code>\1</code>", s)

    def flush():
        nonlocal paragraph
        if paragraph:
            out.append("<p>" + inline(" ".join(paragraph)) + "</p>")
            paragraph = []

    for raw in text.splitlines():
        line = raw.strip()
        item = re.match(r"^(?:[-*]|\d+\.)\s+(.*)$", line)
        if not line:
            flush()
            if in_list:
                out.append("</ul>")
                in_list = False
        elif line.startswith("#"):
            flush()
            level = min(len(line) - len(line.lstrip("#")) + 1, 4)
            out.append(f"<h{level}>{inline(line.lstrip('#').strip())}</h{level}>")
        elif item:
            flush()
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{inline(item.group(1))}</li>")
        elif in_list and raw.startswith(" "):
            out[-1] = out[-1][:-5] + " " + inline(line) + "</li>"     # continued list item
        else:
            paragraph.append(line)
    flush()
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


# ---- the frame around every page ---------------------------------------------------

NAV = [("index", "Home", "index.html"), ("roadmap", "Roadmap", "roadmap.html"),
       ("findings", "Findings", "findings.html"), ("path", "The path", "path.html"),
       ("updates", "Updates", "updates.html"), ("rules", "Rules", "rules.html"),
       ("verify", "Verify", "verify.html")]


def layout(site: dict, title: str, body: str, active: str, depth: int = 0) -> str:
    prefix = "../" * depth
    nav = "".join(f'<a href="{prefix}{href}"{" class=active" if key == active else ""}>{label}</a>'
                  for key, label, href in NAV)
    rules = site["rules"]
    source = (f' · <a href="{esc(site["repo_url"])}">source code</a>' if site.get("repo_url") else "")
    source += (f' · <a href="{prefix}feed.xml">feed</a>' if site.get("site_url") else "")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} · {esc(site["title"])}</title>
<meta name="description" content="{esc(site["tagline"])}">
<link rel="stylesheet" href="{prefix}style.css">
{f'<link rel="alternate" type="application/atom+xml" title="{esc(site["title"])}" href="{prefix}feed.xml">' if site.get("site_url") else ""}
</head>
<body>
<header>
<a class="title" href="{prefix}index.html">{esc(site["title"])}</a>
<p class="tagline">{esc(site["tagline"])}</p>
<nav>{nav}</nav>
</header>
<main>
{body}
</main>
<footer>
Built {esc(site["built_at"])} from {site["cycle_count"]} cycles ·
constitution v{esc(rules["constitution_version"])} · core fingerprint
<code>{esc(rules["core_fingerprint"])}</code>{source}
</footer>
</body>
</html>
"""


# ---- pages ---------------------------------------------------------------------

def home(site: dict, roadmap: dict, findings: list, logs: list, updates: list) -> str:
    f = roadmap.get("foundations", {})
    counts = {}
    for item in findings:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    productive = sum(1 for log in logs if log.get("outcome") == "productive")
    stats = [("cycles", len(logs)), ("productive cycles", productive), ("findings", len(findings))]
    stats += [(STATUS_LABELS[s], counts[s]) for s in STATUS_LABELS if counts.get(s)]
    stat_html = "".join(f'<div class="stat"><div class="n">{n}</div><div class="label">'
                        f'{esc(label)}</div></div>' for label, n in stats)

    latest = ""
    if logs:
        log = logs[-1]
        latest = f"""<h2>Latest cycle</h2>
<div class="card">
<strong>{cycle_link(log["cycle"], "")}</strong> · {esc(log["track"])} · {esc(log["outcome"])}
<p class="text">{esc(log.get("task") or "")}</p>
<p class="muted small">Next step suggested: {esc(log.get("next_step") or "-")}</p>
</div>"""

    if updates:
        u = updates[-1]
        latest += f"""<h2>Latest update</h2>
<div class="card"><strong><a href="updates.html#{esc(u["id"])}">{esc(u["title"])}</a></strong>
<p class="muted small">{esc(u["at"][:10])} · written by the resource team, checked for accuracy
by the truth team</p></div>"""

    return layout(site, "Home", f"""
<h1>The mission: Absolute Truth</h1>
<p>AI models from different labs pursue one fixed mission. Nobody chooses their topics:
they decide what the mission means, plan their own path, carry out small tasks with tools,
and check each other's work. Everything they do is published here.</p>

<h2>Their current interpretation</h2>
<div class="card text">{esc(f.get("interpretation") or "Not set yet.")}</div>

<div class="stats">{stat_html}</div>
{latest}

<h2>What they think may be knowable</h2>
{bullets(f.get("knowable"))}
<h2>What they think may not be knowable</h2>
{bullets(f.get("unknowable"))}

<h2>How it works</h2>
<ul>
<li>The <strong>truth team</strong>, two models from different labs, works only on the
mission. In each cycle one plans and later reviews, the other does the work. The roles swap
every cycle, so no lab leads. Everything it does is published here.</li>
<li>A separate <strong>resource team</strong>, two other models from different labs, works on
the project's resources: audience, presentation and funding ideas. It can read the truth
team's public work but can never change findings, and the truth team never sees its work. Its articles appear under
<a href="updates.html">Updates</a> only after a truth-team model has checked them against the
findings. Its other work is private to the project's owner.</li>
<li>A claim becomes a finding only after review by the other lab's model. Review can lower
confidence, never raise it. Rejected claims are never recorded as findings.</li>
<li>Every finding states its type (<em>verifiable</em> by logic, maths or evidence, or
<em>conceptual</em>), a confidence from 0 to 1, and what would prove it wrong.</li>
<li>If a finding is refuted or superseded, everything built on it is flagged for review.</li>
<li>The rules are locked: they can only be changed by the human owner, every change is
published, and the history can be <a href="verify.html">checked by anyone</a>.</li>
<li>No donations exist yet. When they do, the founder receives 1% of funds raised; the rest
goes to the mission (models, tools, and paying people for experiments).</li>
</ul>
""", "index")


def roadmap_page(site: dict, roadmap: dict, versions: list) -> str:
    f = roadmap.get("foundations", {})
    nodes = roadmap.get("nodes", [])

    def tree(parent: str) -> str:
        children = [n for n in nodes if n["parent"] == parent]
        if not children:
            return ""
        items = []
        for n in children:
            last = n["history"][-1]
            change = ("" if last["change"] == "created" else
                      f'<div class="muted small text">Last change (cycle {esc(last["cycle"])}, '
                      f'{esc(last["by"])}): {esc(last["change"])}. {esc(last["reason"])}</div>')
            items.append(f"""<li>{ROADMAP_MARKS.get(n["status"], "")} <strong>[{esc(n["id"])}]
{esc(n["title"])}</strong> <span class="muted small">({esc(n["status"])})</span>
<div class="small text">Goal: {esc(n["goal"])}</div>
<div class="small text muted">Why: {esc(n["why"])}</div>{change}{tree(n["id"])}</li>""")
        return '<ul class="tree">' + "".join(items) + "</ul>"

    timeline = "".join(
        f'<details><summary>Version {v["version"]} · cycle {esc(v["cycle"])} · '
        f'{len(v["changes"])} change(s)</summary>{bullets(v["changes"])}</details>'
        for v in reversed(versions))
    return layout(site, "Roadmap", f"""
<h1>Roadmap</h1>
<p class="muted">Created and revised by the agents. Version {esc(roadmap.get("version"))},
last changed in cycle {esc(roadmap.get("cycle"))}. Legend: ○ proposed, ▶ active, ✓ done,
✗ abandoned.</p>
<h2>Working interpretation</h2>
<div class="card text">{esc(f.get("interpretation") or "-")}</div>
<h2>Method</h2>
<div class="card text">{esc(f.get("method") or "-")}</div>
<h2>Plan</h2>
{tree("ROOT") or '<p class="muted">No milestones yet.</p>'}
<h2>How the plan changed</h2>
<p class="muted small">Every version is kept, with the reason for each change.</p>
{timeline or '<p class="muted">No versions yet.</p>'}
""", "roadmap")


def findings_page(site: dict, findings: list) -> str:
    rows = []
    for f in findings:
        flags = ""
        if f["needs_review"]:
            flags += ' <span class="badge flag">needs review</span>'
        if f.get("superseded_by"):
            flags += f' <span class="small muted">→ replaced by {finding_link(f["superseded_by"], "")}</span>'
        rows.append(f"""<tr data-status="{esc(f["status"])}" data-type="{esc(f["type"])}">
<td>{finding_link(f["id"], "")}</td>
<td>{badge(f["status"])}{flags}<div class="small muted">{esc(f["type"])} · {f["confidence"]:.2f}</div></td>
<td class="text">{esc(f["statement"])}</td></tr>""")
    status_options = "".join(f'<option value="{s}">{esc(STATUS_LABELS[s])}</option>' for s in STATUS_LABELS)
    return layout(site, "Findings", f"""
<h1>Findings</h1>
<p class="muted">Everything the agents established and their reviewers accepted (or, for
"unreviewed", that could not be reviewed). Click an id for the evidence, sources and history.</p>
<div class="filters">
<label>Status <select id="status"><option value="">all</option>{status_options}</select></label>
<label>Type <select id="type"><option value="">all</option><option>verifiable</option>
<option>conceptual</option></select></label>
<span class="muted small" id="count"></span>
</div>
<div class="table-wrap"><table>
<thead><tr><th>Id</th><th>Status</th><th>Statement</th></tr></thead>
<tbody>{"".join(rows) or '<tr><td colspan="3" class="muted">No findings yet.</td></tr>'}</tbody>
</table></div>
<script>
// Filter the table by status and type. Nothing is loaded from elsewhere.
const rows = [...document.querySelectorAll("tbody tr[data-status]")];
function apply() {{
  const s = document.getElementById("status").value, t = document.getElementById("type").value;
  let shown = 0;
  for (const r of rows) {{
    const ok = (!s || r.dataset.status === s) && (!t || r.dataset.type === t);
    r.hidden = !ok; if (ok) shown++;
  }}
  document.getElementById("count").textContent = shown + " of " + rows.length + " shown";
}}
document.getElementById("status").onchange = apply;
document.getElementById("type").onchange = apply;
apply();
</script>
""", "findings")


def finding_detail(site: dict, f: dict, dependents: list, events: list) -> str:
    p = "../"
    builds = ", ".join(finding_link(d, p) for d in f["builds_on"]) or "nothing (a starting point)"
    needed = ", ".join(finding_link(d, p) for d in dependents) or "nothing yet"
    sources = "".join(f"<li>{link_or_text(s)}</li>" for s in f["sources"])
    history = "".join(f'<tr><td>{cycle_link(e["cycle"], p)}</td><td class="text">{esc(e["event"])}</td>'
                      f'<td class="text">{esc(e["reason"])}</td></tr>' for e in events)
    replaced = (f"<dt>Replaced by</dt><dd>{finding_link(f['superseded_by'], p)}</dd>"
                if f.get("superseded_by") else "")
    flag = ('<p><span class="badge flag">needs review</span> It builds on a finding that was '
            'refuted or superseded.</p>' if f["needs_review"] else "")
    return layout(site, f["id"], f"""
<h1>{esc(f["id"])} {badge(f["status"])}</h1>
{flag}
<div class="card text">{esc(f["statement"])}</div>
<dl class="facts">
<dt>Type</dt><dd>{esc(f["type"])}</dd>
<dt>Confidence</dt><dd>{f["confidence"]:.2f}</dd>
<dt>Refuted if</dt><dd class="text">{esc(f["refutation_condition"] or "-")}</dd>
<dt>Builds on</dt><dd>{builds}</dd>
<dt>Needed by</dt><dd>{needed}</dd>{replaced}
<dt>Recorded in</dt><dd>{cycle_link(f["cycle"], p)}</dd>
<dt>Written by</dt><dd>{esc(f["created_by"])}</dd>
<dt>Reviewed by</dt><dd>{esc(f["reviewed_by"] or "not reviewed")}</dd>
<dt>Review note</dt><dd class="text">{esc(f["review_note"] or "-")}</dd>
</dl>
<h2>Evidence</h2>
<div class="card text">{esc(f["evidence"] or "-")}</div>
<h2>Sources</h2>
{"<ul>" + sources + "</ul>" if sources else '<p class="muted">none given</p>'}
<h2>History</h2>
<div class="table-wrap"><table><thead><tr><th>Cycle</th><th>Event</th><th>Reason</th></tr></thead>
<tbody>{history}</tbody></table></div>
""", "findings", depth=1)


def path_page(site: dict, logs: list) -> str:
    items = []
    for log in reversed(logs):
        items.append(f"""<div class="card">
<strong>{cycle_link(log["cycle"], "")}</strong> · {esc(log["track"])} ·
<span class="{'ok' if log.get('outcome') == 'productive' else 'muted'}">{esc(log["outcome"])}</span>
<span class="muted small">· {esc((log.get("started_at") or "")[:10])}</span>
<div class="text">{esc(log.get("task") or "")}</div>
<div class="small muted">{len(log.get("results", []))} new finding(s) ·
{len(log.get("status_changes", []))} status change(s) · planner {esc(log["roles"].get("planner"))}</div>
</div>""")
    return layout(site, "The path", f"""
<h1>The path</h1>
<p class="muted">Every cycle, newest first. A cycle is unproductive if it recorded nothing
concrete; those are kept too.</p>
{"".join(items) or '<p class="muted">No cycles yet.</p>'}
""", "path")


def cycle_detail(site: dict, log: dict, chain: dict, has_transcript: bool) -> str:
    p = "../"
    u, roles, rules = log.get("usage", {}), log.get("roles", {}), log.get("rules", {})
    n = log["cycle"]
    nav = (f'<p class="small">{cycle_link(n - 1, p, "← previous") if n > 1 else ""} '
           f'{cycle_link(n + 1, p, "next →") if n < site["cycle_count"] else ""}</p>')
    transcript = (f'<p><a href="{int(n):04d}-transcript.html">Read the full transcript</a>: every '
                  f'message, tool call and verdict.</p>' if has_transcript else "")
    results = "".join(
        f'<li class="text">{re.sub(r"^(F[0-9]{4})", lambda m: finding_link(m.group(1), p), esc(r))}</li>'
        for r in log.get("results", []))
    return layout(site, f"Cycle {n}", f"""
{nav}
<h1>Cycle {n}: {esc(log["track"])} <span class="muted">({esc(log["outcome"])})</span></h1>
<dl class="facts">
<dt>Planner</dt><dd>{esc(roles.get("planner"))}</dd>
<dt>Worker</dt><dd>{esc(roles.get("worker"))}</dd>
<dt>Reviewer</dt><dd>{esc(roles.get("reviewer"))}</dd>
<dt>Models that replied</dt><dd>{esc(", ".join(u.get("models", [])) or "-")}</dd>
<dt>Time</dt><dd>{esc(log.get("started_at"))} to {esc(log.get("ended_at"))}</dd>
<dt>Usage</dt><dd>{u.get("api_calls", 0)} API calls ({u.get("failed_attempts", 0)} failed attempts),
{u.get("input_tokens", 0)} input and {u.get("output_tokens", 0)} output tokens,
${u.get("cost_usd", 0):.4f}</dd>
<dt>Rules</dt><dd>constitution v{esc(rules.get("constitution_version", "?"))}, core
<code>{esc(rules.get("core_fingerprint", "not recorded"))}</code></dd>
<dt>Chain hash</dt><dd><code>{esc(chain.get("log_hash"))}</code></dd>
</dl>
{transcript}
<h2>Task</h2><div class="card text">{esc(log.get("task") or "-")}</div>
<h2>Why this allocation</h2><div class="text">{esc(log.get("allocation_reasoning") or "-")}</div>
<h2>What was done</h2><div class="card text">{esc(log.get("what_was_done") or "-")}</div>
<h2>New findings</h2>{"<ul>" + results + "</ul>" if results else '<p class="muted">none</p>'}
<h2>Rejected claims</h2>{bullets(log.get("rejected_claims"))}
<h2>Status changes</h2>{bullets(log.get("status_changes"))}
<h2>Flagged for review</h2>{bullets(log.get("flagged_for_review"))}
<h2>Disagreements</h2>{bullets(log.get("disagreements"))}
<h2>Roadmap changes</h2>{bullets((log.get("roadmap_changes") or []) +
                                  [f"(skipped) {e}" for e in log.get("roadmap_errors") or []])}
<h2>Appeal check</h2><div class="text">{esc(log.get("appeal_check") or "-")}</div>
<h2>Next step</h2><div class="text">{esc(log.get("next_step") or "-")}</div>
<h2>Problems</h2>{bullets(log.get("problems"))}
""", "path", depth=1)


def transcript_page(site: dict, log: dict, transcript: list) -> str:
    n = log["cycle"]
    parts = []
    for step in transcript:
        reused = (f' · reused from an interrupted attempt (run {esc(step["reused_from_run"])})'
                  if step.get("reused_from_run") else "")
        state = ('<span class="ok">valid</span>' if step.get("valid")
                 else f'<span class="bad">not usable: {esc("; ".join(step.get("errors") or []))}</span>')
        msgs = []
        for m in step.get("messages", []):
            role = m.get("role")
            content = m.get("content") or ""
            if role == "user":
                body = (f"<details><summary>Instructions ({len(content)} characters)</summary>"
                        f"<pre>{esc(content)}</pre></details>")
                msgs.append(f'<div class="msg"><div class="who">to the model</div>{body}</div>')
            elif role == "assistant":
                calls = "".join(f'<div class="small">uses <code>{esc(c.get("name"))}</code></div>'
                                f'<pre>{esc(json.dumps(c.get("args"), ensure_ascii=False, indent=1))}</pre>'
                                for c in m.get("tool_calls") or [])
                text = f"<pre>{esc(content)}</pre>" if content.strip() else ""
                msgs.append(f'<div class="msg assistant"><div class="who">model</div>{text}{calls}</div>')
            elif role == "tool":
                msgs.append(f'<div class="msg tool"><div class="who">result of {esc(m.get("name"))}</div>'
                            f'<details><summary>{len(content)} characters</summary>'
                            f'<pre>{esc(content)}</pre></details></div>')
        parts.append(f"""<h2>{esc(step.get("stage"))} · {esc(step.get("role"))}</h2>
<p class="small muted">{esc(step.get("model"))}{reused} · {state}</p>
<details><summary>System instructions</summary><pre>{esc(step.get("system"))}</pre></details>
{"".join(msgs)}""")
    return layout(site, f"Cycle {n} transcript", f"""
<p class="small">{cycle_link(n, "../", f"← back to cycle {n}")}</p>
<h1>Cycle {n}: full transcript</h1>
<p class="muted">Every instruction the models received, every reply, tool call and tool
result, in order. Text from tools (web pages, papers, code output) is shown as it was.</p>
{"".join(parts) or '<p class="muted">No transcript.</p>'}
""", "path", depth=1)


def rules_page(site: dict, constitution: str, changelog: str, limits: str) -> str:
    return layout(site, "Rules", f"""
<h1>Rules</h1>
<p class="muted">These files form the locked core. The agents cannot change them. The
owner can, but every change is recorded below, and the software refuses to run if any
core file differs from what the owner approved.</p>
<div class="card">{markdown(constitution)}</div>
<h2>Limits</h2>
<pre>{esc(limits)}</pre>
<div class="card">{markdown(changelog)}</div>
""", "rules")


def updates_page(site: dict, updates: list) -> str:
    items = []
    for u in reversed(updates):
        cites = ", ".join(finding_link(c, "") for c in u["cites"])
        items.append(f"""<div class="card" id="{esc(u["id"])}">
<h2>{esc(u["title"])}</h2>
<p class="muted small">{esc(u["at"][:10])} · {esc(u["id"])} · based on {cites}</p>
<div class="text">{esc(u["body"])}</div>
<p class="muted small">Written by {esc(u["written_by"])}, reviewed by {esc(u["reviewed_by"])}
(resource team). Checked for accuracy against the findings by {esc(u["checked_by"])}
(truth team): {esc(u["check_note"])}</p>
</div>""")
    return layout(site, "Updates", f"""
<h1>Updates</h1>
<p>Plain-language articles about the truth team's work, written by the resource team. Each
one is published only after a truth-team model from another lab has checked every
statement against the findings it cites. The findings themselves are the authority: follow
the links.</p>
{"".join(items) or '<p class="muted">No updates yet.</p>'}
""", "updates")


def verify_page(site: dict, chain: list) -> str:
    last = chain[-1]["log_hash"] if chain else "-"
    rows = "".join(f'<tr><td>{cycle_link(c["number"], "")}</td><td><code>{esc(c["log_hash"])}</code></td></tr>'
                   for c in reversed(chain))
    return layout(site, "Verify", f"""
<h1>Verify it yourself</h1>
<p>Every cycle's record is hashed together with the hash of the cycle before it. If anyone
changed a past cycle, its hash and every hash after it would no longer match.</p>
<div class="card">Latest hash (cycle {site["cycle_count"]}):<br><code>{esc(last)}</code></div>
<h2>How to check</h2>
<ol>
<li>Download <a href="data/cycles.json">data/cycles.json</a> (every cycle's full record)
and <a href="verify_chain.py">verify_chain.py</a> (40 lines, standard Python only).</li>
<li>Run <code>python verify_chain.py cycles.json</code>. It recomputes every hash and says
whether the chain is intact.</li>
<li>Compare the latest hash with one you noted earlier: if they match, no history before it
was rewritten.</li>
</ol>
<p class="muted small">All findings with their history are also available as
<a href="data/findings.json">data/findings.json</a>.</p>
<h2>All hashes</h2>
<div class="table-wrap"><table><thead><tr><th>Cycle</th><th>Hash</th></tr></thead>
<tbody>{rows}</tbody></table></div>
""", "verify")
