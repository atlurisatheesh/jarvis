"""Skill registry. Each skill module exposes SKILLS = [(schema, fn), ...].

`TOOLS` is the list of tool schemas handed to the LLM.
`run_tool(name, args)` dispatches a tool call to the matching function.
"""
from . import (system, files, web, media, notes, phone,
               reminders, routines, desktop, docs, farm, universal, timer, windows,
               vision, context, email, google)

_modules = [system, files, web, media, notes, phone,
            reminders, routines, desktop, docs, farm, universal, timer, windows,
            vision, context, email, google]

TOOLS = []          # Ollama/OpenAI-style tool schemas
DISPATCH = {}       # name -> python function

for _m in _modules:
    for _schema, _fn in _m.SKILLS:
        TOOLS.append({"type": "function", "function": _schema})
        DISPATCH[_schema["name"]] = _fn


def run_tool(name: str, args: dict) -> str:
    fn = DISPATCH.get(name)
    if not fn:
        return f"Unknown tool: {name}"
    try:
        return str(fn(**(args or {})))
    except Exception as e:
        return f"Error running {name}: {e}"
