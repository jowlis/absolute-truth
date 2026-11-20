"""Free public lookups available to every worker: Wikipedia and arXiv.

Both are public APIs that need no key. Results are returned as plain text with
links, so findings can cite them as sources.
"""

import json
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


def _get(url: str, cfg: dict) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": cfg["user_agent"]})
    with urllib.request.urlopen(request, timeout=cfg["timeout_seconds"]) as response:
        return response.read()


def wikipedia_search(query: str, cfg: dict) -> str:
    params = urllib.parse.urlencode({
        "action": "query", "list": "search", "srsearch": query, "format": "json",
        "srlimit": cfg["max_results"], "srprop": "snippet"})
    data = json.loads(_get(f"https://en.wikipedia.org/w/api.php?{params}", cfg))
    hits = data.get("query", {}).get("search", [])
    if not hits:
        return "No Wikipedia results."

    # Fetch the plain-text introduction of each result.
    titles = "|".join(h["title"] for h in hits)
    params = urllib.parse.urlencode({
        "action": "query", "prop": "extracts", "exintro": 1, "explaintext": 1,
        "titles": titles, "format": "json", "exlimit": "max"})
    pages = json.loads(_get(f"https://en.wikipedia.org/w/api.php?{params}", cfg))
    intros = {p.get("title"): p.get("extract", "")
              for p in pages.get("query", {}).get("pages", {}).values()}

    parts = []
    for h in hits:
        title = h["title"]
        url = "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))
        intro = (intros.get(title) or "").strip()[:1200]
        parts.append(f"## {title}\n{url}\n{intro}")
    return "\n\n".join(parts)


def arxiv_search(query: str, cfg: dict) -> str:
    params = urllib.parse.urlencode({
        "search_query": f"all:{query}", "start": 0, "max_results": cfg["max_results"]})
    root = ET.fromstring(_get(f"https://export.arxiv.org/api/query?{params}", cfg))
    ns = {"a": "http://www.w3.org/2005/Atom"}
    parts = []
    for entry in root.findall("a:entry", ns):
        title = " ".join((entry.findtext("a:title", "", ns)).split())
        link = entry.findtext("a:id", "", ns)
        published = entry.findtext("a:published", "", ns)[:10]
        authors = ", ".join(a.findtext("a:name", "", ns) for a in entry.findall("a:author", ns))
        summary = " ".join(entry.findtext("a:summary", "", ns).split())[:1200]
        parts.append(f"## {title}\n{link} ({published}; {authors})\n{summary}")
    return "\n\n".join(parts) or "No arXiv results."
