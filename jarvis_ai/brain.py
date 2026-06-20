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

class Brain:
    def __init__(self):
        engine = config.BRAIN_ENGINE
        if engine == "groq" and config.GROQ_API_KEY:
            print("[brain] engine: Groq cloud (llama-3.3-70b-versatile)")
            self._groq = _GroqBrain()
            self._local = None
        elif engine == "auto" and config.GROQ_API_KEY:
            print("[brain] engine: auto (Groq cloud -> local Ollama fallback)")
            self._groq = _GroqBrain()
            self._local = _LocalBrain()
        else:
            print(f"[brain] engine: local Ollama ({config.BRAIN_MODEL})")
            self._groq = None
            self._local = _LocalBrain()

    def ask(self, user_text: str) -> str:
        if self._groq:
            try:
                return self._groq.ask(user_text)
            except _GroqRateLimited:
                if self._local:
                    print("[brain] Groq rate limited; answering with local Ollama.")
                    return self._local.ask(user_text)
                return "I cannot reach my cloud brain right now, Sir."
            except Exception as e:
                print(f"[brain] Groq error: {e}")
                if self._local:
                    print("[brain] falling back to local Ollama...")
                    return self._local.ask(user_text)
                return "Cloud brain unavailable and no local fallback, Sir."
        return self._local.ask(user_text)

    def ask_stream(self, user_text: str) -> Generator[str, None, None]:
        """Yield reply tokens for low-latency pipeline TTS. Groq only; local falls back to full reply."""
        if self._groq:
            try:
                yield from self._groq.ask_stream(user_text)
                return
            except _GroqRateLimited:
                if self._local:
                    print("[brain] Groq stream rate limited; answering with local Ollama.")
                    yield self._local.ask(user_text)
                    return
                yield "I cannot reach my cloud brain right now, Sir."
                return
            except Exception as e:
                print(f"[brain] Groq stream error: {e}")
                if self._local:
                    yield self._local.ask(user_text)
                    return
                yield "Cloud brain unavailable, Sir."
                return
        yield self._local.ask(user_text)
