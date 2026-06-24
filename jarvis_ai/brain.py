"""The brain: Groq cloud LLM (fast, smart) with local Ollama fallback.

Engine selection via config.BRAIN_ENGINE:
  "groq"  — cloud llama-3.1-8b-instant via Groq
  "local" — local Ollama qwen2.5:3b on CPU
  "auto"  — try Groq first, fall back to local on network error (recommended)

ask()        — full reply (blocking)
ask_stream() — yields tokens as they arrive; enables pipeline TTS for <0.5s perceived latency
"""
import json
import time
from typing import Generator

import ollama
import requests

from . import config, memory, skills
from .runtime_state import runtime


def _system_prompt() -> str:
    prompt = config.SYSTEM_PROMPT
    facts = memory.all_facts()
    if facts:
        prompt += "\nKnown facts about the user:\n- " + "\n- ".join(facts)
    return prompt


def _openai_tools() -> list:
    """Convert Ollama-style tool schemas to OpenAI function-calling format.
    Filtered to GROQ_TOOL_ALLOWLIST to keep requests small (rate limits)."""
    allow = getattr(config, "GROQ_TOOL_ALLOWLIST", None)
    out = []
    for t in skills.TOOLS:
        fn = t.get("function", t)
        if allow and fn["name"] not in allow:
            continue
        out.append({
            "type": "function",
            "function": {
                "name": fn["name"],
                "description": fn.get("description", ""),
                "parameters": fn.get("parameters", {"type": "object", "properties": {}}),
            }
        })
    return out


# ── Groq cloud brain ────────────────────────────────────────────────
_GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
_OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"


class _GroqRateLimited(RuntimeError):
    """A throttled cloud model should not stall the always-on voice loop."""


class _GroqBrain:
    def __init__(self):
        self.messages = [{"role": "system", "content": _system_prompt()}]
        self._tools = _openai_tools()

    def _trim(self, keep: int = 20):
        if len(self.messages) > keep + 1:
            self.messages = [self.messages[0]] + self.messages[-keep:]

    def _clean_messages(self):
        """Sanitize history so Groq never sees stale tool_calls / tool msgs
        from prior completed turns. Only the *current* tool round should have them."""
        clean = []
        for m in self.messages:
            cm = dict(m)
            # Strip tool_calls from old assistant messages (already resolved)
            if cm["role"] == "assistant" and "tool_calls" in cm:
                # keep it only if the very next msg is a tool response
                idx = self.messages.index(m)
                if idx + 1 < len(self.messages) and self.messages[idx + 1].get("role") == "tool":
                    clean.append(cm)
                else:
                    clean.append({"role": "assistant", "content": cm.get("content") or ""})
            elif cm["role"] == "tool":
                clean.append(cm)
            else:
                clean.append(cm)
        return clean

    def ask(self, user_text: str) -> str:
        self.messages.append({"role": "user", "content": user_text})
        for _ in range(5):
            payload = {
                "model": config.GROQ_BRAIN_MODEL,
                "messages": self._clean_messages(),
                "tools": self._tools,
                "tool_choice": "auto",
                "max_tokens": config.BRAIN_NUM_PREDICT,
            }
            r = requests.post(
                _GROQ_CHAT_URL,
                headers={
                    "Authorization": f"Bearer {config.GROQ_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=config.GROQ_TIMEOUT_SECONDS,
            )
            if not r.ok:
                # Retrying a throttled model freezes an always-on assistant.
                # Keep it optional, but default to a fast spoken status instead.
                if r.status_code == 429:
                    retry_seconds = max(0, int(getattr(config, "GROQ_RATE_LIMIT_RETRY_SECONDS", 0)))
                    if retry_seconds:
                        print(f"[brain] Groq rate limited, waiting {retry_seconds}s and retrying...")
                        time.sleep(retry_seconds)
                        r = requests.post(
                            _GROQ_CHAT_URL,
                            headers={
                                "Authorization": f"Bearer {config.GROQ_API_KEY}",
                                "Content-Type": "application/json",
                            },
                            json=payload,
                            timeout=config.GROQ_TIMEOUT_SECONDS,
                        )
                    if r.status_code == 429:
                        raise _GroqRateLimited("Groq rate limit reached")
                # 8b sometimes hallucinates a tool name -> 400 tool_use_failed.
                # Retry once WITHOUT tools to get a plain text answer.
                if r.status_code == 400 and "tool_use_failed" in r.text:
                    print("[brain] tool hallucination, retrying without tools...")
                    p2 = dict(payload)
                    p2.pop("tools", None)
                    p2["tool_choice"] = "none"
                    r = requests.post(
                        _GROQ_CHAT_URL,
                        headers={
                            "Authorization": f"Bearer {config.GROQ_API_KEY}",
                            "Content-Type": "application/json",
                        },
                        json=p2,
                        timeout=config.GROQ_TIMEOUT_SECONDS,
                    )
                if not r.ok:
                    print(f"[brain] Groq HTTP {r.status_code}: {r.text[:200]}")
                    r.raise_for_status()
            choice = r.json()["choices"][0]
            msg = choice["message"]

            # normalise for our message history
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                hist_msg = {"role": "assistant", "content": None, "tool_calls": tool_calls}
            else:
                hist_msg = {"role": "assistant", "content": msg.get("content") or ""}
            self.messages.append(hist_msg)

            if not tool_calls:
                self._trim()
                return (msg.get("content") or "").strip()

            for tc in tool_calls:
                fn = tc["function"]
                name = fn["name"]
                try:
                    args = json.loads(fn["arguments"]) if isinstance(fn["arguments"], str) else fn["arguments"]
                except (json.JSONDecodeError, TypeError):
                    args = {}
                result = skills.run_tool(name, args)
                print(f"[tool] {name}({args}) -> {result}")
                if name == "play_youtube":
                    self._trim()
                    return str(result)
                self.messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": str(result),
                })
        self._trim()
        return "I got stuck handling that, Sir."

    def ask_stream(self, user_text: str) -> Generator[str, None, None]:
        """Stream reply tokens for low-latency TTS pipeline.

        Pure text responses are yielded token-by-token so TTS can start
        speaking the first sentence while the rest is still generating.
        Tool calls fall back to non-streaming execution then yield the result.
        """
        self.messages.append({"role": "user", "content": user_text})
        payload = {
            "model": config.GROQ_BRAIN_MODEL,
            "messages": self._clean_messages(),
            "tools": self._tools,
            "tool_choice": "auto",
            "max_tokens": config.BRAIN_NUM_PREDICT,
            "stream": True,
        }
        try:
            r = requests.post(
                _GROQ_CHAT_URL,
                headers={
                    "Authorization": f"Bearer {config.GROQ_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
                stream=True,
                timeout=config.GROQ_TIMEOUT_SECONDS,
            )
            if not r.ok:
                if r.status_code == 429:
                    raise _GroqRateLimited("Groq rate limit reached")
                raise requests.HTTPError(response=r)
        except _GroqRateLimited:
            # Let the dispatcher choose the local fallback. Calling ask() here
            # only turns a quota error into a spoken "brain busy" message.
            raise
        except Exception as e:
            print(f"[brain] stream failed: {e}, falling back to non-stream")
            yield self.ask(user_text)
            return

        # Parse SSE stream
        content = ""
        tool_calls_acc: dict = {}  # index -> {id, name, arguments}

        for raw_line in r.iter_lines():
            line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
            if not line.startswith("data: "):
                continue
            data_str = line[6:]
            if data_str == "[DONE]":
                break
            try:
                chunk = json.loads(data_str)
            except (json.JSONDecodeError, ValueError):
                continue

            choices = chunk.get("choices", [])
            if not choices:
                continue
            delta = choices[0].get("delta", {})

            # Accumulate tool call deltas
            for tc in (delta.get("tool_calls") or []):
                i = tc.get("index", 0)
                if i not in tool_calls_acc:
                    tool_calls_acc[i] = {"id": "", "name": "", "arguments": ""}
                if tc.get("id"):
                    tool_calls_acc[i]["id"] = tc["id"]
                fn = tc.get("function", {})
                if fn.get("name"):
                    tool_calls_acc[i]["name"] += fn["name"]
                if fn.get("arguments"):
                    tool_calls_acc[i]["arguments"] += fn["arguments"]

            # Yield text tokens immediately (enables pipeline TTS)
            text = delta.get("content") or ""
            if text and not tool_calls_acc:
                content += text
                yield text

        if tool_calls_acc:
            # Tool call path: build tool_calls list, execute, get final reply
            tool_calls = []
            for i in sorted(tool_calls_acc.keys()):
                tc = tool_calls_acc[i]
                tool_calls.append({
                    "id": tc["id"] or f"tc_{i}",
                    "type": "function",
                    "function": {"name": tc["name"], "arguments": tc["arguments"]},
                })
            self.messages.append({"role": "assistant", "content": None, "tool_calls": tool_calls})

            for tc in tool_calls:
                fn = tc["function"]
                name = fn["name"]
                try:
                    args = json.loads(fn["arguments"]) if isinstance(fn["arguments"], str) else fn["arguments"]
                except (json.JSONDecodeError, TypeError):
                    args = {}
                result = skills.run_tool(name, args)
                print(f"[tool] {name}({args}) -> {result}", flush=True)
                if name == "play_youtube":
                    self._trim()
                    yield str(result)
                    return
                self.messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": str(result),
                })

            # Get final answer after tool results (non-streaming, fast)
            p2 = {
                "model": config.GROQ_BRAIN_MODEL,
                "messages": self._clean_messages(),
                "max_tokens": config.BRAIN_NUM_PREDICT,
            }
            try:
                r2 = requests.post(
                    _GROQ_CHAT_URL,
                    headers={
                        "Authorization": f"Bearer {config.GROQ_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json=p2,
                    timeout=config.GROQ_TIMEOUT_SECONDS,
                )
                r2.raise_for_status()
                reply = r2.json()["choices"][0]["message"].get("content", "").strip()
                self.messages.append({"role": "assistant", "content": reply})
            except Exception as e:
                print(f"[brain] tool follow-up failed: {e}")
                reply = str(result)
            self._trim()
            yield reply
        else:
            if content:
                self.messages.append({"role": "assistant", "content": content})
            self._trim()


# ── Local Ollama brain ──────────────────────────────────────────────

class _OpenAIBrain:
    """Cloud fallback for normal conversational turns when Groq is throttled."""

    def __init__(self):
        self.messages = [{"role": "system", "content": _system_prompt()}]

    def _trim(self, keep: int = 12):
        if len(self.messages) > keep + 1:
            self.messages = [self.messages[0]] + self.messages[-keep:]

    def ask(self, user_text: str) -> str:
        self.messages.append({"role": "user", "content": user_text})
        response = requests.post(
            _OPENAI_CHAT_URL,
            headers={
                "Authorization": f"Bearer {config.OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": config.OPENAI_BRAIN_MODEL,
                "messages": self.messages,
                "max_tokens": config.BRAIN_NUM_PREDICT,
            },
            timeout=config.OPENAI_BRAIN_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        reply = response.json()["choices"][0]["message"].get("content", "").strip()
        self.messages.append({"role": "assistant", "content": reply})
        self._trim()
        return reply


class _CloudflareBrain:
    """Cloudflare Workers AI — primary brain (OpenAI-compatible, Llama-3.3-70B).

    Supports tool-calling like Groq. Warm latency ~1s; cold-start can be ~30s,
    so Brain keeps it warm with a periodic ping.
    """

    def __init__(self):
        self.messages = [{"role": "system", "content": _system_prompt()}]
        self._tools = _openai_tools()
        self.url = (f"https://api.cloudflare.com/client/v4/accounts/"
                    f"{config.CLOUDFLARE_ACCOUNT_ID}/ai/v1/chat/completions")
        self._headers = {
            "Authorization": f"Bearer {config.CLOUDFLARE_API_TOKEN}",
            "Content-Type": "application/json",
        }

    def _trim(self, keep: int = 12):
        if len(self.messages) > keep + 1:
            self.messages = [self.messages[0]] + self.messages[-keep:]

    def warmup(self):
        """Cheap ping to keep the 70B model loaded (avoids 30s cold-start)."""
        try:
            requests.post(self.url, headers=self._headers, json={
                "model": config.CF_BRAIN_MODEL,
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 1,
            }, timeout=config.CF_BRAIN_TIMEOUT_SECONDS)
        except Exception:
            pass

    def ask(self, user_text: str) -> str:
        self.messages.append({"role": "user", "content": user_text})
        for _ in range(5):
            r = requests.post(self.url, headers=self._headers, json={
                "model": config.CF_BRAIN_MODEL,
                "messages": self.messages,
                "tools": self._tools,
                "tool_choice": "auto",
                "max_tokens": config.BRAIN_NUM_PREDICT,
            }, timeout=config.CF_BRAIN_TIMEOUT_SECONDS)
            r.raise_for_status()
            msg = r.json()["choices"][0]["message"]
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                self.messages.append({"role": "assistant", "content": msg.get("content"),
                                      "tool_calls": tool_calls})
            else:
                reply = (msg.get("content") or "").strip()
                self.messages.append({"role": "assistant", "content": reply})
                self._trim()
                return reply
            for tc in tool_calls:
                fn = tc["function"]
                name = fn["name"]
                try:
                    args = json.loads(fn["arguments"]) if isinstance(fn["arguments"], str) else (fn["arguments"] or {})
                except (json.JSONDecodeError, TypeError):
                    args = {}
                result = skills.run_tool(name, args)
                print(f"[tool] {name}({args}) -> {result}")
                if name == "play_youtube":
                    self._trim()
                    return str(result)
                self.messages.append({"role": "tool", "tool_call_id": tc.get("id", ""),
                                      "content": str(result)})
        self._trim()
        return "I got stuck handling that, Sir."

    def ask_stream(self, user_text: str) -> Generator[str, None, None]:
        """Stream tokens from Cloudflare Workers AI (OpenAI-compatible SSE)."""
        self.messages.append({"role": "user", "content": user_text})
        try:
            r = requests.post(self.url, headers=self._headers, json={
                "model": config.CF_BRAIN_MODEL,
                "messages": self.messages,
                "tools": self._tools,
                "tool_choice": "auto",
                "max_tokens": config.BRAIN_NUM_PREDICT,
                "stream": True,
            }, stream=True, timeout=config.CF_BRAIN_TIMEOUT_SECONDS)
            r.raise_for_status()
        except Exception as e:
            print(f"[brain] CF stream failed: {e}, falling back to non-stream")
            yield self.ask(user_text)
            return

        content = ""
        tool_calls_acc: dict = {}
        for raw_line in r.iter_lines():
            line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
            if not line.startswith("data: "):
                continue
            data_str = line[6:]
            if data_str == "[DONE]":
                break
            try:
                chunk = json.loads(data_str)
            except (json.JSONDecodeError, ValueError):
                continue
            choices = chunk.get("choices", [])
            if not choices:
                continue
            delta = choices[0].get("delta", {})
            for tc in (delta.get("tool_calls") or []):
                i = tc.get("index", 0)
                if i not in tool_calls_acc:
                    tool_calls_acc[i] = {"id": "", "name": "", "arguments": ""}
                if tc.get("id"):
                    tool_calls_acc[i]["id"] = tc["id"]
                fn = tc.get("function", {})
                if fn.get("name"):
                    tool_calls_acc[i]["name"] += fn["name"]
                if fn.get("arguments"):
                    tool_calls_acc[i]["arguments"] += fn["arguments"]
            text = delta.get("content") or ""
            if text and not tool_calls_acc:
                content += text
                yield text

        if tool_calls_acc:
            tool_calls = []
            for i in sorted(tool_calls_acc.keys()):
                tc = tool_calls_acc[i]
                tool_calls.append({
                    "id": tc["id"] or f"tc_{i}",
                    "type": "function",
                    "function": {"name": tc["name"], "arguments": tc["arguments"]},
                })
            self.messages.append({"role": "assistant", "content": None, "tool_calls": tool_calls})
            for tc in tool_calls:
                fn = tc["function"]
                name = fn["name"]
                try:
                    args = json.loads(fn["arguments"]) if isinstance(fn["arguments"], str) else (fn["arguments"] or {})
                except (json.JSONDecodeError, TypeError):
                    args = {}
                result = skills.run_tool(name, args)
                print(f"[tool] {name}({args}) -> {result}", flush=True)
                if name == "play_youtube":
                    self._trim()
                    yield str(result)
                    return
                self.messages.append({"role": "tool", "tool_call_id": tc.get("id", ""),
                                      "content": str(result)})
            try:
                r2 = requests.post(self.url, headers=self._headers, json={
                    "model": config.CF_BRAIN_MODEL,
                    "messages": self.messages,
                    "max_tokens": config.BRAIN_NUM_PREDICT,
                }, timeout=config.CF_BRAIN_TIMEOUT_SECONDS)
                r2.raise_for_status()
                reply = r2.json()["choices"][0]["message"].get("content", "").strip()
                self.messages.append({"role": "assistant", "content": reply})
                self._trim()
                yield reply
            except Exception as e:
                print(f"[brain] CF tool follow-up failed: {e}")
                yield str(result)
        else:
            if content:
                self.messages.append({"role": "assistant", "content": content})
            self._trim()


class _LocalBrain:
    def __init__(self):
        self.client = ollama.Client(host=config.OLLAMA_HOST)
        self.messages = [{"role": "system", "content": _system_prompt()}]

    def _trim(self, keep: int = 20):
        if len(self.messages) > keep + 1:
            self.messages = [self.messages[0]] + self.messages[-keep:]

    def ask(self, user_text: str) -> str:
        self.messages.append({"role": "user", "content": user_text})
        for _ in range(5):
            resp = self.client.chat(
                model=config.BRAIN_MODEL,
                messages=self.messages,
                tools=skills.TOOLS,
                keep_alive=config.BRAIN_KEEP_ALIVE,
                options={"num_predict": config.BRAIN_NUM_PREDICT},
            )
            msg = resp["message"]
            self.messages.append(msg)
            tool_calls = msg.get("tool_calls")
            if not tool_calls:
                self._trim()
                return (msg.get("content") or "").strip()
            for tc in tool_calls:
                fn = tc["function"]
                name = fn["name"]
                args = fn.get("arguments", {}) or {}
                result = skills.run_tool(name, args)
                print(f"[tool] {name}({args}) -> {result}")
                if name == "play_youtube":
                    self._trim()
                    return str(result)
                self.messages.append({"role": "tool", "name": name, "content": result})
        self._trim()
        return "I got stuck handling that, Sir."


# ── Public Brain class (dispatcher) ─────────────────────────────────

def _cf_available() -> bool:
    return bool(
        getattr(config, "CF_BRAIN_ENABLED", False)
        and config.CLOUDFLARE_ACCOUNT_ID
        and config.CLOUDFLARE_API_TOKEN
    )


class Brain:
    """Ordered brain chain. Preferred order: Cloudflare -> Groq -> OpenAI -> local.

    Each tier is tried until one answers; a throttled/erroring tier falls through
    to the next. Cloudflare (Llama-3.3-70B) is primary; kept warm to dodge the
    ~30s cold-start.
    """

    def __init__(self):
        engine = config.BRAIN_ENGINE
        self._cloudflare = _CloudflareBrain() if _cf_available() else None
        self._groq = _GroqBrain() if config.GROQ_API_KEY else None
        self._openai = _OpenAIBrain() if config.OPENAI_API_KEY else None
        # keep a local brain unless explicitly groq-only with cloud available
        self._local = None if (engine == "groq" and config.GROQ_API_KEY) else _LocalBrain()
        # Circuit breakers per provider (Phase 2).  We keep ``_cooldowns`` for
        # backward compatibility with older tests, but the breakers are the
        # source of truth.
        from .circuit_breaker import CircuitBreaker
        cb_fail = getattr(config, "CB_FAILURE_THRESHOLD", 3)
        cb_open = getattr(config, "PROVIDER_COOLDOWN_SECONDS", 45)
        cb_half = getattr(config, "CB_HALF_OPEN_SECONDS", 30)
        self._breakers: dict[str, "CircuitBreaker"] = {}
        self._cooldowns: dict[str, float] = {}  # legacy compat
        for pname in ("cloudflare", "groq", "openai"):
            self._breakers[pname] = CircuitBreaker(
                name=pname, failure_threshold=cb_fail,
                open_seconds=cb_open, half_open_seconds=cb_half,
            )
        self.last_provider = ""
        self.last_latency_ms = 0.0

        names = []
        if self._cloudflare: names.append("Cloudflare")
        if self._groq: names.append("Groq")
        if self._openai: names.append("OpenAI")
        if self._local: names.append("local Ollama")
        print(f"[brain] chain: {' -> '.join(names) or 'none'}")

        if self._cloudflare:
            self._start_keepwarm()

    def _start_keepwarm(self):
        import threading
        def loop():
            while True:
                self._cloudflare.warmup()
                time.sleep(120)  # every 2 min keeps the 70B model loaded
        threading.Thread(target=loop, daemon=True).start()

    def _chain(self):
        return [b for b in (getattr(self, "_cloudflare", None), getattr(self, "_groq", None),
                            getattr(self, "_openai", None), getattr(self, "_local", None)) if b]

    @staticmethod
    def _provider_name(brain) -> str:
        explicit_name = getattr(brain, "provider_name", "")
        if explicit_name:
            return str(explicit_name)
        if isinstance(brain, _CloudflareBrain):
            return "cloudflare"
        if isinstance(brain, _GroqBrain):
            return "groq"
        if isinstance(brain, _OpenAIBrain):
            return "openai"
        return "ollama"

    def _ready(self, brain) -> bool:
        name = self._provider_name(brain)
        # Circuit breaker path (Phase 2).  Some legacy tests build a Brain via
        # __new__ (no __init__), so guard against missing attributes.
        breakers = getattr(self, "_breakers", None)
        if breakers is not None:
            breaker = breakers.get(name)
            if breaker is not None:
                if not breaker.allow_request():
                    print(f"[brain] {name} circuit {breaker.state}; skipping.", flush=True)
                    return False
                return True
        # Legacy cooldown path for ollama (no breaker) / older callers
        until = getattr(self, "_cooldowns", {}).get(name, 0.0)
        if until > time.monotonic():
            print(f"[brain] {name} cooling down for {until - time.monotonic():.0f}s; skipping.", flush=True)
            return False
        return True

    def _success(self, brain, started: float):
        name = self._provider_name(brain)
        self.last_provider = name
        self.last_latency_ms = round((time.perf_counter() - started) * 1000, 1)
        runtime.provider(name)
        runtime.timing("brain", self.last_latency_ms)
        getattr(self, "_cooldowns", {}).pop(name, None)
        breakers = getattr(self, "_breakers", None)
        if breakers is not None:
            breaker = breakers.get(name)
            if breaker is not None:
                breaker.record_success()

    def _failure(self, brain, error: Exception):
        name = self._provider_name(brain)
        breakers = getattr(self, "_breakers", None)
        if breakers is not None:
            breaker = breakers.get(name)
            if breaker is not None:
                breaker.record_failure()
                print(f"[brain] {name} unavailable ({error}); circuit={breaker.state}.", flush=True)
                return
        # Ollama is the last local fallback. Do not cool it down, because it is
        # better to return its direct error than leave the chain empty.
        if name != "ollama":
            cooldowns = getattr(self, "_cooldowns", None)
            if cooldowns is None:
                cooldowns = {}
                self._cooldowns = cooldowns
            cooldowns[name] = time.monotonic() + config.PROVIDER_COOLDOWN_SECONDS
            print(f"[brain] {name} unavailable ({error}); cooling down for {config.PROVIDER_COOLDOWN_SECONDS}s.", flush=True)

    def ask(self, user_text: str) -> str:
        for b in self._chain():
            if not self._ready(b):
                continue
            started = time.perf_counter()
            try:
                reply = b.ask(user_text)
                self._success(b, started)
                return reply
            except _GroqRateLimited as e:
                self._failure(b, e)
                continue
            except Exception as e:
                self._failure(b, e)
                print(f"[brain] {type(b).__name__} error: {e}; next tier.")
                continue
        return "All my brains are unreachable right now, Sir."

    def ask_stream(self, user_text: str) -> Generator[str, None, None]:
        """Stream tokens when the primary tier supports it (Groq); otherwise yield
        the full reply from the first tier that answers."""
        chain = self._chain()
        for b in chain:
            if not self._ready(b):
                continue
            started = time.perf_counter()
            try:
                if isinstance(b, _GroqBrain):
                    first_token = True
                    for token in b.ask_stream(user_text):
                        if first_token:
                            runtime.timing("brain_first_token", (time.perf_counter() - started) * 1000)
                            first_token = False
                        yield token
                    self._success(b, started)
                    return
                reply = b.ask(user_text)
                self._success(b, started)
                yield reply
                return
            except _GroqRateLimited as e:
                self._failure(b, e)
                continue
            except Exception as e:
                self._failure(b, e)
                print(f"[brain] {type(b).__name__} stream error: {e}; next tier.")
                continue
        yield "All my brains are unreachable right now, Sir."
