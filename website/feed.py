"""An Atom feed (feed.xml) so people can follow the project in a feed reader.

It lists the newest public updates, findings and cycles, each linking to its page on the
site. Like the rest of the website it only reads the data, escapes all agent text and
contains no tracking. The feed reader asks for the file; nothing is sent back.
"""

from xml.sax.saxutils import escape

MAX_ENTRIES = 50


def _entry(site_url: str, entry_id: str, title: str, path: str, when: str, summary: str) -> dict:
    return {"id": f"{site_url}{path}#{entry_id}", "title": title, "link": f"{site_url}{path}",
            "updated": when, "summary": summary}


def atom(site: dict, findings: list, logs: list, updates: list) -> str:
    url = site["site_url"].rstrip("/") + "/"
    entries = []
    for u in updates:
        entries.append(_entry(url, u["id"], f"Update: {u['title']}", f"updates.html#{u['id']}",
                              u["at"], u["body"]))
    for f in findings:
        title = (f"{f['id']} ({f['status']}, {f['type']}, confidence {f['confidence']:.2f}): "
                 f"{f['statement'][:120]}")
        entries.append(_entry(url, f["id"], title, f"findings/{f['id']}.html",
                              f["updated_at"] or f["created_at"], f["statement"]))
    for log in logs:
        n = log["cycle"]
        entries.append(_entry(url, f"cycle-{n}", f"Cycle {n} ({log['outcome']}): {log.get('task') or '-'}",
                              f"cycles/{n:04d}.html", log.get("ended_at") or log["started_at"],
                              log.get("what_was_done") or ""))
    entries.sort(key=lambda e: e["updated"], reverse=True)
    entries = entries[:MAX_ENTRIES]
    newest = entries[0]["updated"] if entries else "1970-01-01T00:00:00+00:00"

    def item(e: dict) -> str:
        return f"""<entry>
<id>{escape(e["id"])}</id>
<title>{escape(e["title"])}</title>
<link href="{escape(e["link"], {'"': "&quot;"})}"/>
<updated>{escape(e["updated"])}</updated>
<summary>{escape(e["summary"])}</summary>
</entry>"""

    return f"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<id>{escape(url)}</id>
<title>{escape(site["title"])}</title>
<subtitle>{escape(site["tagline"])}</subtitle>
<link href="{escape(url)}"/>
<link rel="self" href="{escape(url)}feed.xml"/>
<updated>{escape(newest)}</updated>
<author><name>{escape(site["title"])}</name></author>
{chr(10).join(item(e) for e in entries)}
</feed>
"""
