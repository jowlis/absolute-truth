"""The tools a worker or reviewer can call, and how each call is carried out.

Tool definitions use plain JSON Schema; each agent adapter converts them to its
provider's format. Tool results are data for the agent, never instructions.
"""

from core.budget import BudgetExceeded, DailyQuotaReached
from core.killswitch import StopRequested
from tools import lookup, sandbox

RUN_PYTHON = {
    "name": "run_python",
    "description": ("Run Python 3 code in an isolated sandbox with no network and no files, "
                    "and get its printed output. Use it for calculations, simulations and "
                    "logic checks. Print what you want to see. Available: the standard "
                    "library plus numpy, scipy, sympy and mpmath (if one is missing, the "
                    "error says so)."),
    "parameters": {"type": "object",
                   "properties": {"code": {"type": "string", "description": "Python code"}},
                   "required": ["code"]},
}
WEB_SEARCH = {
    "name": "web_search",
    "description": "Search the web. Returns a short answer with source links.",
    "parameters": {"type": "object",
                   "properties": {"query": {"type": "string"}}, "required": ["query"]},
}
WIKIPEDIA_SEARCH = {
    "name": "wikipedia_search",
    "description": "Search English Wikipedia. Returns article introductions with links.",
    "parameters": {"type": "object",
                   "properties": {"query": {"type": "string"}}, "required": ["query"]},
}
ARXIV_SEARCH = {
    "name": "arxiv_search",
    "description": "Search arXiv scientific papers. Returns titles, links and abstracts.",
    "parameters": {"type": "object",
                   "properties": {"query": {"type": "string"}}, "required": ["query"]},
}


class Toolbox:
    def __init__(self, agent, config: dict, sandbox_ok: bool):
        self.agent = agent
        self.config = config
        self.definitions = [WIKIPEDIA_SEARCH, ARXIV_SEARCH]
        if sandbox_ok:
            self.definitions.insert(0, RUN_PYTHON)
        if agent.cfg.get("web_search") and not agent.web_search_off:
            self.definitions.insert(0, WEB_SEARCH)

    def names(self) -> list[str]:
        return [d["name"] for d in self.definitions]

    def run(self, name: str, args: dict) -> str:
        if name not in self.names():
            return f"[error] Unknown or unavailable tool: {name}"
        try:
            if name == "run_python":
                return sandbox.run_python(str(args.get("code", "")), self.config["sandbox"])
            if name == "web_search":
                return self.agent.web_search(str(args.get("query", "")))
            if name == "wikipedia_search":
                return lookup.wikipedia_search(str(args.get("query", "")), self.config["lookup"])
            if name == "arxiv_search":
                return lookup.arxiv_search(str(args.get("query", "")), self.config["lookup"])
        except (StopRequested, BudgetExceeded, DailyQuotaReached):
            raise  # limits always win, even inside a tool
        except Exception as e:  # any other tool failure must not crash the cycle
            return f"[error] {name} failed: {type(e).__name__}: {e}"
        return f"[error] {name} has no handler"
