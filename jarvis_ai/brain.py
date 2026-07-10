"""The brain: Groq cloud LLM (fast, smart) with local Ollama fallback.

Engine selection via config.BRAIN_ENGINE:
  "groq"  — cloud llama-3.1-8b-instant via Groq
  "local" — local Ollama qwen2.5:3b on CPU
  "auto"  — try Groq first, fall back to local on network error (recommended)

ask()        — full reply (blocking)
ask_stream() — yields tokens as they arrive; enables pipeline TTS for <0.5s perceived latency
"""
import json
import re
import time
from typing import Generator

import ollama
import requests

from . import config, memory, skills
from . import conversation_store
from . import language
from .runtime_state import runtime


def _system_prompt() -> str:
    prompt = config.SYSTEM_PROMPT
    prompt += "\n" + language.prompt_language_rule()
    facts = memory.all_facts()
    if facts:
        prompt += "\nKnown facts about the user:\n- " + "\n- ".join(facts)
    return prompt


def _initial_messages() -> list[dict]:
    """Build the opening message list: system prompt + rehydrated prior turns.

    Every provider brain starts with a system message. When conversation
    persistence is enabled, the last few turns from the previous session are
    spliced in so the model remembers the thread after a restart.
    """
    msgs = [{"role": "system", "content": _system_prompt()}]
    try:
        prior = conversation_store.load_recent(
            int(getattr(config, "CONVERSATION_REHYDRATE_TURNS", 4))
        )
        if prior:
            lines = []
            for turn in prior:
                user = str(turn.get("user", "")).strip()[:240]
                assistant = str(turn.get("assistant", "")).strip()[:320]
                if user and assistant:
                    lines.append(f"User previously: {user}\nAssistant previously: {assistant}")
            if lines:
                msgs.append({
                    "role": "system",
                    "content": (
                        "Historical conversation context follows. Use it only "
                        "for continuity. Never repeat an old tool call, action, "
                        "or answer unless the current user explicitly asks.\n\n"
                        + "\n\n".join(lines)
                    ),
                })
    except Exception:
        pass
    return msgs


def _with_semantic_memory(user_text: str) -> str:
    """Optionally add semantic memory context to a user turn.

    Disabled by default because embeddings add latency. Explicit memory-search
    voice commands still use semantic recall even when injection is off.
    """
    if not getattr(config, "SEMANTIC_MEMORY_INJECT_ENABLED", False):
        return user_text
    try:
        from . import semantic_memory
        ctx = semantic_memory.context_for(user_text)
    except Exception:
        ctx = ""
    if not ctx:
        return user_text
    return f"{ctx}\n\nCurrent request: {user_text}"


def _final_answer_instruction(user_text: str) -> str:
    """Provider-local instruction to prevent reasoning text in spoken replies."""
    if language.is_indian_language(user_text):
        script_rule = (
            "The user used English letters for an Indian language. Reply in the native Indian script "
            "for correct text-to-speech pronunciation, not romanized English letters. "
            if language.is_romanized_indian_language(user_text)
            else ""
        )
        return (
            "Reply with only the final answer in the same Indian language. "
            f"{script_rule}"
            "No English explanation. No reasoning. No <think> text. Request: "
            f"{user_text}"
        )
    return user_text


def _clean_provider_reply(text: str) -> str:
    """Remove leaked reasoning/tool wrappers from hosted models before TTS."""
    reply = (text or "").strip()
    if "</think>" in reply:
        reply = reply.split("</think>", 1)[1].strip()
    if "<think>" in reply:
        before, _, after = reply.partition("<think>")
        reply = (before + " " + after).strip()

    # Some non-tool-calling providers occasionally emit function-call markup as
    # text. Never speak those hidden control fragments to the user.
    reply = re.sub(r"<function=[^>]*>.*?</function>", "", reply, flags=re.DOTALL | re.IGNORECASE).strip()
    reply = re.sub(r"<tool_call>.*?</tool_call>", "", reply, flags=re.DOTALL | re.IGNORECASE).strip()
    reply = re.sub(r"```(?:json)?\s*\{[^`]*(?:\"tool\"|\"function\"|\"arguments\"|\"command\")[^`]*\}\s*```", "", reply, flags=re.DOTALL | re.IGNORECASE).strip()
    reply = re.sub(r"<\|[^|]+?\|>", "", reply, flags=re.DOTALL).strip()

    for prefix in (
        "Okay, the user wants",
        "Okay, the user asked",
        "The user asked",
        "Let me recall",
        "I need to",
        "I know that",
    ):
        if reply.lower().startswith(prefix.lower()):
            indic = re.search(r"[\u0900-\u097f\u0980-\u09ff\u0a80-\u0aff\u0b00-\u0b7f\u0b80-\u0bff\u0c00-\u0c7f\u0c80-\u0cff\u0d00-\u0d7f][^\"'\n<>()]*", reply)
            if indic:
                return indic.group(0).strip(" .,:;")
            lines = [line.strip() for line in reply.splitlines() if line.strip()]
            reply = lines[-1] if lines else reply
            break
    return reply.strip() or "I heard you, Sir."


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
        self.messages = _initial_messages()
        self._tools = _openai_tools()

    def warmup(self):
        """Cheap ping to warm the Groq connection (avoids cold-start latency)."""
        try:
            requests.post(
                _GROQ_CHAT_URL,
                headers={
                    "Authorization": f"Bearer {config.GROQ_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": config.GROQ_BRAIN_MODEL,
                    "messages": [{"role": "user", "content": "hi"}],
                    "max_tokens": 1,
                },
                timeout=config.GROQ_TIMEOUT_SECONDS,
            )
        except Exception:
            pass

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
        self.messages.append({"role": "user", "content": _with_semantic_memory(user_text)})
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
        self.messages.append({"role": "user", "content": _with_semantic_memory(user_text)})
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
        emitted = 0       # chars of `content` already yielded to TTS
        leaked = False    # model wrote tool markup as plain text
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

            # Yield text tokens immediately (enables pipeline TTS). Some
            # models leak tool-call markup as plain text ("<function=...");
            # never speak that. Tokens are held back while the tail could be
            # the start of a markup tag, so fragments like "Sir, <" are never
            # spoken either.
            text = delta.get("content") or ""
            if text and not tool_calls_acc:
                content += text
                if leaked or "<function" in content or "<tool_call" in content:
                    leaked = True
                    continue
                hold = 0
                for marker in ("<function", "<tool_call"):
                    for k in range(len(marker), 0, -1):
                        if content.endswith(marker[:k]):
                            hold = max(hold, k)
                            break
                emit_to = len(content) - hold
                if emit_to > emitted:
                    yield content[emitted:emit_to]
                    emitted = emit_to

        if not tool_calls_acc and not leaked and emitted < len(content):
            yield content[emitted:]
            emitted = len(content)

        if not tool_calls_acc and leaked:
            # The model wrote a tool call as text instead of calling it.
            # Re-ask without tools for a plain spoken answer.
            print("[brain] tool markup leaked in stream; re-asking without tools", flush=True)
            try:
                p2 = {
                    "model": config.GROQ_BRAIN_MODEL,
                    "messages": self._clean_messages() + [{
                        "role": "user",
                        "content": (
                            "Answer the previous question directly in one short "
                            "spoken sentence. Never mention tools, functions, "
                            "commands, or what you would need to do."
                        ),
                    }],
                    "max_tokens": config.BRAIN_NUM_PREDICT,
                    "tool_choice": "none",
                }
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
                reply = _clean_provider_reply(r2.json()["choices"][0]["message"].get("content", ""))
                content = reply
                yield reply
            except Exception as e:
                print(f"[brain] leak-recovery retry failed: {e}")
                content = ""

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
        self.messages = _initial_messages()

    def _trim(self, keep: int = 12):
        if len(self.messages) > keep + 1:
            self.messages = [self.messages[0]] + self.messages[-keep:]

    def ask(self, user_text: str) -> str:
        self.messages.append({"role": "user", "content": _with_semantic_memory(user_text)})
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
        self.messages = _initial_messages()
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
        self.messages.append({"role": "user", "content": _with_semantic_memory(user_text)})
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
                reply = _clean_provider_reply(msg.get("content") or "")
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
        self.messages.append({"role": "user", "content": _with_semantic_memory(user_text)})
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
                if "<function" in content or "<tool_call" in content:
                    continue
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
                reply = _clean_provider_reply(r2.json()["choices"][0]["message"].get("content", ""))
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


# ── NVIDIA hosted brain ─────────────────────────────────────────────

class _NvidiaSarvamBrain:
    """NVIDIA OpenAI-compatible brain.

    Default model is z-ai/glm-5.2 via NVIDIA's integrate.api.nvidia.com.
    """
    provider_name = "nvidia"

    def __init__(self):
        self.messages = _initial_messages()
        self._tools = _openai_tools()
        self._base_url = config.NVIDIA_BASE_URL.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {config.NVIDIA_API_KEY}",
            "Content-Type": "application/json",
        }

    def _trim(self, keep: int = 12):
        if len(self.messages) > keep + 1:
            self.messages = [self.messages[0]] + self.messages[-keep:]

    def _clean_messages(self):
        """Sanitize history (same logic as _GroqBrain)."""
        clean = []
        for m in self.messages:
            cm = dict(m)
            if cm["role"] == "assistant" and "tool_calls" in cm:
                idx = self.messages.index(m)
                if idx + 1 < len(self.messages) and self.messages[idx + 1].get("role") == "tool":
                    clean.append(cm)
                else:
                    clean.append({"role": "assistant", "content": cm.get("content") or ""})
            else:
                clean.append(cm)
        return clean

    def _model_for(self, user_text: str) -> str:
        if (
            getattr(config, "NVIDIA_INDIAN_LANGUAGE_MODEL", "")
            and language.is_indian_language(user_text)
        ):
            return config.NVIDIA_INDIAN_LANGUAGE_MODEL
        return config.NVIDIA_BRAIN_MODEL

    def _max_tokens_for(self, user_text: str) -> int:
        if self._model_for(user_text) == getattr(config, "NVIDIA_INDIAN_LANGUAGE_MODEL", ""):
            return max(int(config.BRAIN_NUM_PREDICT), 512)
        return int(config.BRAIN_NUM_PREDICT)

    def ask(self, user_text: str) -> str:
        self.messages.append({"role": "user", "content": _with_semantic_memory(_final_answer_instruction(user_text))})
        for _ in range(5):
            model = self._model_for(user_text)
            indian = model == getattr(config, "NVIDIA_INDIAN_LANGUAGE_MODEL", "")
            if indian:
                # NVIDIA's sarvam-m endpoint rejects tool-calling requests and
                # any history it deems malformed ("System message can only be
                # the first message!"). Send a minimal fresh conversation:
                # system prompt + the current user turn only.
                payload = {
                    "model": model,
                    "messages": [self.messages[0], self.messages[-1]],
                    "max_tokens": self._max_tokens_for(user_text),
                    "temperature": 0.5,
                    "top_p": 1,
                }
            else:
                payload = {
                    "model": model,
                    "messages": self._clean_messages(),
                    "tools": self._tools,
                    "tool_choice": "auto",
                    "max_tokens": self._max_tokens_for(user_text),
                    "temperature": 0.5,
                    "top_p": 1,
                }
            r = requests.post(
                f"{self._base_url}/chat/completions",
                headers=self._headers,
                json=payload,
                timeout=config.NVIDIA_BRAIN_TIMEOUT_SECONDS,
            )
            if not r.ok:
                if r.status_code == 429:
                    raise _GroqRateLimited("NVIDIA rate limit reached")
                # Tool hallucination fallback — retry without tools
                if r.status_code == 400 and "tool" in r.text.lower():
                    print("[brain] nvidia tool error, retrying without tools...")
                    p2 = dict(payload)
                    p2.pop("tools", None)
                    p2.pop("tool_choice", None)
                    r = requests.post(
                        f"{self._base_url}/chat/completions",
                        headers=self._headers,
                        json=p2,
                        timeout=config.NVIDIA_BRAIN_TIMEOUT_SECONDS,
                    )
                if not r.ok:
                    print(f"[brain] NVIDIA HTTP {r.status_code}: {r.text[:200]}")
                    r.raise_for_status()
            choice = r.json()["choices"][0]
            msg = choice["message"]
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                self.messages.append({"role": "assistant", "content": None, "tool_calls": tool_calls})
            else:
                reply = _clean_provider_reply(msg.get("content") or "")
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
                self.messages.append({"role": "tool", "tool_call_id": tc.get("id", ""), "content": str(result)})
        self._trim()
        return "I got stuck handling that, Sir."

    def ask_stream(self, user_text: str) -> Generator[str, None, None]:
        """Stream tokens from NVIDIA Sarvam-M (OpenAI-compatible SSE)."""
        model = self._model_for(user_text)
        if model == getattr(config, "NVIDIA_INDIAN_LANGUAGE_MODEL", ""):
            yield self.ask(user_text)
            return

        self.messages.append({"role": "user", "content": _with_semantic_memory(_final_answer_instruction(user_text))})
        try:
            r = requests.post(
                f"{self._base_url}/chat/completions",
                headers=self._headers,
                json={
                    "model": model,
                    "messages": self._clean_messages(),
                    "max_tokens": self._max_tokens_for(user_text),
                    "temperature": 0.5,
                    "top_p": 1,
                    "stream": True,
                },
                stream=True,
                timeout=config.NVIDIA_BRAIN_TIMEOUT_SECONDS,
            )
            if not r.ok:
                if r.status_code == 429:
                    raise _GroqRateLimited("NVIDIA rate limit reached")
                raise requests.HTTPError(response=r)
        except _GroqRateLimited:
            raise
        except Exception as e:
            print(f"[brain] nvidia stream failed: {e}, falling back to non-stream")
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
                if "<function" in content or "<tool_call" in content:
                    continue
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
                self.messages.append({"role": "tool", "tool_call_id": tc.get("id", ""), "content": str(result)})
            try:
                r2 = requests.post(
                    f"{self._base_url}/chat/completions",
                    headers=self._headers,
                    json={
                        "model": model,
                        "messages": self._clean_messages(),
                        "max_tokens": config.BRAIN_NUM_PREDICT,
                    },
                    timeout=config.NVIDIA_BRAIN_TIMEOUT_SECONDS,
                )
                r2.raise_for_status()
                reply = _clean_provider_reply(r2.json()["choices"][0]["message"].get("content", ""))
                self.messages.append({"role": "assistant", "content": reply})
                self._trim()
                yield reply
            except Exception as e:
                print(f"[brain] nvidia tool follow-up failed: {e}")
                yield str(result)
        else:
            if content:
                self.messages.append({"role": "assistant", "content": content})
            self._trim()


class _SarvamAIBrain:
    """Direct Sarvam AI chat fallback for Indian-language turns."""

    provider_name = "sarvam_ai"

    def __init__(self):
        self.messages = _initial_messages()
        self._base_url = config.SARVAM_BASE_URL.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {config.SARVAM_API_KEY}",
            "api-subscription-key": config.SARVAM_API_KEY,
            "Content-Type": "application/json",
        }

    def _trim(self, keep: int = 10):
        if len(self.messages) > keep + 1:
            self.messages = [self.messages[0]] + self.messages[-keep:]

    def ask(self, user_text: str) -> str:
        if not language.is_indian_language(user_text):
            raise RuntimeError("Sarvam AI fallback is reserved for Indian-language turns")
        self.messages.append({"role": "user", "content": _with_semantic_memory(_final_answer_instruction(user_text))})
        payload = {
            "model": config.SARVAM_CHAT_MODEL,
            "messages": self.messages,
            "max_tokens": max(int(config.BRAIN_NUM_PREDICT), 512),
            "temperature": 0.2,
        }
        r = requests.post(
            f"{self._base_url}/chat/completions",
            headers=self._headers,
            json=payload,
            timeout=config.SARVAM_TIMEOUT_SECONDS,
        )
        if not r.ok:
            print(f"[brain] Sarvam AI HTTP {r.status_code}: {r.text[:200]}")
            r.raise_for_status()
        msg = r.json()["choices"][0]["message"]
        reply = _clean_provider_reply(msg.get("content") or "")
        self.messages.append({"role": "assistant", "content": reply})
        self._trim()
        return reply

    def ask_stream(self, user_text: str) -> Generator[str, None, None]:
        yield self.ask(user_text)


class _LocalBrain:
    def __init__(self):
        self.client = ollama.Client(host=config.OLLAMA_HOST)
        self.messages = _initial_messages()

    def _trim(self, keep: int = 20):
        if len(self.messages) > keep + 1:
            self.messages = [self.messages[0]] + self.messages[-keep:]

    def ask(self, user_text: str) -> str:
        self.messages.append({"role": "user", "content": _with_semantic_memory(user_text)})
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
    """Ordered brain chain.

    English turns: Groq -> Cloudflare -> OpenAI -> local Ollama (qwen, last
    resort only). Indian-language turns: NVIDIA sarvam-m -> Sarvam direct ->
    the same English chain. Each tier is tried until one answers; a throttled
    or erroring tier falls through to the next. Cloudflare is kept warm to
    dodge its ~30s cold-start.
    """

    def __init__(self):
        engine = config.BRAIN_ENGINE
        self._cloudflare = _CloudflareBrain() if _cf_available() else None
        self._nvidia = _NvidiaSarvamBrain() if getattr(config, "NVIDIA_BRAIN_ENABLED", False) else None
        self._sarvam_ai = _SarvamAIBrain() if getattr(config, "SARVAM_AI_ENABLED", False) else None
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
        for pname in ("cloudflare", "nvidia", "sarvam_ai", "groq", "openai"):
            self._breakers[pname] = CircuitBreaker(
                name=pname, failure_threshold=cb_fail,
                open_seconds=cb_open, half_open_seconds=cb_half,
            )
        self.last_provider = ""
        self.last_latency_ms = 0.0

        names = []
        for provider in self._chain():
            pname = self._provider_name(provider)
            if pname == "nvidia":
                indian = getattr(config, "NVIDIA_INDIAN_LANGUAGE_MODEL", "")
                if indian:
                    names.append(f"NVIDIA {config.NVIDIA_BRAIN_MODEL} / Indian {indian}")
                else:
                    names.append(f"NVIDIA {config.NVIDIA_BRAIN_MODEL}")
            elif pname == "sarvam_ai":
                names.append(f"Sarvam AI {config.SARVAM_CHAT_MODEL}")
            elif pname == "cloudflare":
                names.append("Cloudflare")
            elif pname == "groq":
                names.append("Groq")
            elif pname == "openai":
                names.append("OpenAI")
            else:
                names.append("local Ollama")
        if self._sarvam_ai and not any(name.startswith("Sarvam AI") for name in names):
            names.insert(1 if names else 0, f"Sarvam AI {config.SARVAM_CHAT_MODEL} (Indian fallback)")
        print(f"[brain] chain: {' -> '.join(names) or 'none'}")

        if self._cloudflare:
            self._start_keepwarm()
        if self._groq:
            import threading
            threading.Thread(target=self._groq.warmup, daemon=True).start()

    def _start_keepwarm(self):
        import threading
        def loop():
            while True:
                self._cloudflare.warmup()
                time.sleep(120)  # every 2 min keeps the 70B model loaded
        threading.Thread(target=loop, daemon=True).start()

    def _chain(self, user_text: str = ""):
        indian_turn = language.is_indian_language(user_text or "")
        nvidia = getattr(self, "_nvidia", None)
        if nvidia and not indian_turn and not getattr(config, "NVIDIA_BRAIN_ENGLISH_ENABLED", False):
            nvidia = None
        sarvam_direct = getattr(self, "_sarvam_ai", None) if indian_turn else None
        if getattr(config, "NVIDIA_BRAIN_PRIORITY", True):
            # Indian turns: NVIDIA sarvam-m, then Sarvam direct. English turns:
            # Groq first — it has the lowest first-token latency of the cloud
            # tiers, which keeps spoken replies feeling instant. Local Ollama
            # (qwen) is always the last offline fallback.
            order = (
                nvidia,
                sarvam_direct,
                getattr(self, "_groq", None),
                getattr(self, "_cloudflare", None),
                getattr(self, "_openai", None),
                getattr(self, "_local", None),
            )
        else:
            order = (
                getattr(self, "_cloudflare", None),
                nvidia,
                sarvam_direct,
                getattr(self, "_groq", None),
                getattr(self, "_openai", None),
                getattr(self, "_local", None),
            )
        return [b for b in order if b]

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
        if isinstance(brain, _SarvamAIBrain):
            return "sarvam_ai"
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
        for b in self._chain(user_text):
            if not self._ready(b):
                continue
            started = time.perf_counter()
            try:
                reply = b.ask(user_text)
                self._success(b, started)
                conversation_store.save_turn(user_text, reply)
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
        """Stream tokens from the first available provider that supports it.

        Cloudflare and Groq both expose ``ask_stream``. Older code only used
        Groq streaming, which made a configured Cloudflare primary brain wait
        for the full reply before speech could begin.
        """
        for b in self._chain(user_text):
            if not self._ready(b):
                continue
            started = time.perf_counter()
            emitted = False
            try:
                streamer = getattr(b, "ask_stream", None)
                if callable(streamer):
                    first_token = True
                    for token in streamer(user_text):
                        if not token:
                            continue
                        if first_token:
                            runtime.timing("brain_first_token", (time.perf_counter() - started) * 1000)
                            first_token = False
                        emitted = True
                        yield token
                    self._success(b, started)
                    return
                reply = b.ask(user_text)
                self._success(b, started)
                yield reply
                return
            except _GroqRateLimited as e:
                self._failure(b, e)
                # Once speech has started, switching providers would append a
                # second answer to the first one. Preserve the partial reply
                # and let the next user turn retry with the fallback chain.
                if emitted:
                    print("[brain] stream ended after speech started; suppressing duplicate fallback.", flush=True)
                    return
                continue
            except Exception as e:
                self._failure(b, e)
                print(f"[brain] {type(b).__name__} stream error: {e}; next tier.")
                if emitted:
                    print("[brain] stream ended after speech started; suppressing duplicate fallback.", flush=True)
                    return
                continue
        yield "All my brains are unreachable right now, Sir."
