"""Adapter for Google Gemini (google-genai SDK).

Web search uses Gemini's built-in Google Search grounding, run as a separate call so it
works alongside our own tools on every Gemini model.
"""

from google import genai
from google.genai import errors, types

from agents.base import Agent, RateLimited, Reply, ToolCall, Transient

try:  # the HTTP library google-genai uses (httpx2 in recent versions, httpx before)
    import httpx2 as _http
except ImportError:
    import httpx as _http

NETWORK_ERRORS = (_http.TimeoutException, _http.TransportError, TimeoutError, ConnectionError)


class GeminiAgent(Agent):
    def __init__(self, key, cfg, budget, api_key: str, on_usage=None):
        super().__init__(key, cfg, budget, on_usage)
        # The timeout (in ms) also tells Google's servers how long they may take.
        # The library's own retries are off: all retries happen in Agent._guarded,
        # where every attempt is counted against the daily quota.
        self.client = genai.Client(api_key=api_key, http_options=types.HttpOptions(
            timeout=int(cfg["timeout_seconds"] * 1000),
            retry_options=types.HttpRetryOptions(attempts=1)))

    def _chat(self, system: str, messages: list, tools: list) -> Reply:
        config = types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=self.cfg["max_output_tokens"],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        if tools:
            config.tools = [types.Tool(function_declarations=[
                types.FunctionDeclaration(name=t["name"], description=t["description"],
                                          parameters_json_schema=t["parameters"])
                for t in tools])]
        response = self._call(lambda: self.client.models.generate_content(
            model=self.cfg["model"], contents=_to_contents(messages), config=config))

        content = response.candidates[0].content if response.candidates else None
        parts = (content.parts or []) if content else []
        text = "".join(p.text for p in parts if p.text and not p.thought)
        calls = [ToolCall(id=p.function_call.id or f"call_{i}", name=p.function_call.name,
                          args=dict(p.function_call.args or {}))
                 for i, p in enumerate(parts) if p.function_call]
        finish = str(response.candidates[0].finish_reason) if response.candidates else ""
        return Reply(text=text, tool_calls=calls, raw=content, truncated="MAX_TOKENS" in finish,
                     **_usage(response))

    def _web_search(self, query: str) -> Reply:
        config = types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
            max_output_tokens=2048)
        prompt = (f"Search the web for: {query}\n"
                  "Summarize what the sources say, factually and briefly. Note disagreements.")
        response = self._call(lambda: self.client.models.generate_content(
            model=self.cfg["model"], contents=prompt, config=config))
        text = response.text or ""
        sources = []
        candidate = response.candidates[0] if response.candidates else None
        metadata = candidate.grounding_metadata if candidate else None
        for chunk in (metadata.grounding_chunks or []) if metadata else []:
            if chunk.web:
                sources.append(f"- {chunk.web.title}: {chunk.web.uri}")
        if sources:
            text += "\n\nSources:\n" + "\n".join(sources)
        return Reply(text=text or "No results.", **_usage(response))

    def list_models(self) -> list[str]:
        names = []
        for m in self.client.models.list():
            actions = m.supported_actions or []
            if "generateContent" in actions:
                names.append(m.name.removeprefix("models/"))
        return sorted(names)

    @staticmethod
    def _call(fn):
        try:
            return fn()
        except errors.APIError as e:
            if e.code == 429:
                raise RateLimited(str(e)) from e
            if e.code and e.code >= 500:
                raise Transient(str(e)) from e
            raise
        except NETWORK_ERRORS as e:
            raise Transient(f"{type(e).__name__}: {e}") from e


def _usage(response) -> dict:
    u = response.usage_metadata
    if u is None:
        return {"input_tokens": 0, "output_tokens": 0}
    # Thinking tokens are billed as output.
    return {"input_tokens": u.prompt_token_count or 0,
            "output_tokens": (u.candidates_token_count or 0) + (u.thoughts_token_count or 0)}


def _to_contents(messages: list) -> list:
    """Neutral messages -> Gemini contents. Consecutive tool results go into one turn."""
    contents = []
    for m in messages:
        if m["role"] == "user":
            contents.append(types.Content(role="user", parts=[types.Part.from_text(text=m["content"])]))
        elif m["role"] == "assistant":
            # Send Gemini's own message back unchanged (it carries thought signatures).
            contents.append(m.get("raw") or types.Content(
                role="model", parts=[types.Part.from_text(text=m["content"] or "")]))
        elif m["role"] == "tool":
            part = types.Part.from_function_response(name=m["name"], response={"result": m["content"]})
            part.function_response.id = m["tool_call_id"]
            last = contents[-1] if contents else None
            if last is not None and last.role == "user" and all(p.function_response for p in last.parts):
                last.parts.append(part)
            else:
                contents.append(types.Content(role="user", parts=[part]))
    return contents
