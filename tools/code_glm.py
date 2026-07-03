#!/usr/bin/env python3
"""Coding assistant powered by NVIDIA GLM (z-ai/glm-5.2).

Store your API key in D:\\jarvis\\.nvidia_key or set NVIDIA_API_KEY.

Examples:
  python tools/code_glm.py "How do I refactor this loop to use a generator?"
  python tools/code_glm.py -f jarvis_ai/brain.py "Explain the NVIDIA brain class"
  python tools/code_glm.py --file src/main.py --file src/util.py "Find bugs"
  python tools/code_glm.py          # interactive REPL
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jarvis_ai import config  # noqa: E402

USE_COLOR = sys.stdout.isatty() and os.getenv("NO_COLOR") is None
REASONING_COLOR = "\033[90m" if USE_COLOR else ""
RESET_COLOR = "\033[0m" if USE_COLOR else ""
BOLD = "\033[1m" if USE_COLOR else ""

CODING_SYSTEM_PROMPT = """You are an expert software engineer helping with coding tasks.
Be precise and practical. Prefer showing working code over long prose.
When editing code, show complete snippets or clear diffs — not vague descriptions.
Ask clarifying questions only when requirements are genuinely ambiguous.
Match the project's language, style, and conventions when file context is provided."""

MAX_FILE_CHARS = 120_000


def _die(msg: str, code: int = 1) -> None:
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(code)


def _load_files(paths: list[str]) -> str:
    blocks: list[str] = []
    total = 0
    for raw in paths:
        path = Path(raw)
        if not path.is_file():
            _die(f"file not found: {path}")
        text = path.read_text(encoding="utf-8", errors="replace")
        if total + len(text) > MAX_FILE_CHARS:
            remaining = MAX_FILE_CHARS - total
            if remaining <= 0:
                break
            text = text[:remaining] + "\n... [truncated]"
        blocks.append(f"--- {path.as_posix()} ---\n{text}")
        total += len(text)
    return "\n\n".join(blocks)


def _build_user_message(prompt: str, file_paths: list[str]) -> str:
    if not file_paths:
        return prompt
    context = _load_files(file_paths)
    return (
        "Use the file context below when answering.\n\n"
        f"{context}\n\n"
        f"Question:\n{prompt}"
    )


def _headers() -> dict[str, str]:
    if not config.NVIDIA_API_KEY:
        _die(
            "NVIDIA API key missing. Create D:\\jarvis\\.nvidia_key "
            "or set NVIDIA_API_KEY, then retry."
        )
    return {
        "Authorization": f"Bearer {config.NVIDIA_API_KEY}",
        "Content-Type": "application/json",
    }


def _stream_completion(
    messages: list[dict],
    *,
    model: str,
    max_tokens: int,
    temperature: float,
    show_reasoning: bool,
) -> str:
    base_url = config.NVIDIA_BASE_URL.rstrip("/")
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "top_p": 1,
        "max_tokens": max_tokens,
        "stream": True,
    }

    try:
        r = requests.post(
            f"{base_url}/chat/completions",
            headers=_headers(),
            json=payload,
            stream=True,
            timeout=max(120, config.NVIDIA_BRAIN_TIMEOUT_SECONDS),
        )
    except requests.RequestException as exc:
        _die(f"request failed: {exc}")

    if not r.ok:
        _die(f"NVIDIA HTTP {r.status_code}: {r.text[:400]}")

    assistant = ""
    reasoning_started = False
    for raw_line in r.iter_lines():
        line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
        if not line.startswith("data: "):
            continue
        data_str = line[6:]
        if data_str == "[DONE]":
            break
        try:
            chunk = json.loads(data_str)
        except json.JSONDecodeError:
            continue

        choices = chunk.get("choices") or []
        if not choices:
            continue
        delta = choices[0].get("delta") or {}

        reasoning = (
            delta.get("reasoning_content")
            or delta.get("reasoning")
            or delta.get("thinking")
        )
        if reasoning and show_reasoning:
            if not reasoning_started:
                print(f"{REASONING_COLOR}{BOLD}thinking{RESET_COLOR}", end="", flush=True)
                reasoning_started = True
            print(f"{REASONING_COLOR}{reasoning}{RESET_COLOR}", end="", flush=True)

        text = delta.get("content")
        if text:
            if reasoning_started:
                print(f"\n\n{BOLD}answer{RESET_COLOR}\n", end="", flush=True)
                reasoning_started = False
            assistant += text
            print(text, end="", flush=True)

    if reasoning_started or assistant:
        print()
    return assistant.strip()


def _chat_once(
    history: list[dict],
    user_text: str,
    *,
    model: str,
    max_tokens: int,
    temperature: float,
    show_reasoning: bool,
) -> str:
    history.append({"role": "user", "content": user_text})
    reply = _stream_completion(
        history,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        show_reasoning=show_reasoning,
    )
    history.append({"role": "assistant", "content": reply})
    return reply


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Coding assistant using NVIDIA GLM (OpenAI-compatible API)."
    )
    parser.add_argument(
        "prompt",
        nargs="?",
        help="Question or task. Omit to start interactive mode.",
    )
    parser.add_argument(
        "-f",
        "--file",
        action="append",
        default=[],
        dest="files",
        help="Attach file context (repeatable).",
    )
    parser.add_argument(
        "--model",
        default=config.NVIDIA_BRAIN_MODEL,
        help=f"Model id (default: {config.NVIDIA_BRAIN_MODEL}).",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=16384,
        help="Max output tokens (default: 16384).",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.2,
        help="Sampling temperature (default: 0.2 for coding).",
    )
    parser.add_argument(
        "--hide-reasoning",
        action="store_true",
        help="Do not print model reasoning/thinking tokens.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    show_reasoning = not args.hide_reasoning
    history: list[dict] = [{"role": "system", "content": CODING_SYSTEM_PROMPT}]

    if args.prompt:
        user_text = _build_user_message(args.prompt, args.files)
        _chat_once(
            history,
            user_text,
            model=args.model,
            max_tokens=args.max_tokens,
            temperature=args.temperature,
            show_reasoning=show_reasoning,
        )
        return

    print(f"GLM coding REPL ({args.model}). Ctrl+C or /exit to quit.")
    if args.files:
        print(f"Loaded files: {', '.join(args.files)}")

    while True:
        try:
            line = input("\ncode> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line or line in {"/exit", "/quit", "exit", "quit"}:
            break
        _chat_once(
            history,
            _build_user_message(line, args.files),
            model=args.model,
            max_tokens=args.max_tokens,
            temperature=args.temperature,
            show_reasoning=show_reasoning,
        )


if __name__ == "__main__":
    main()
