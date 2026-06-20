"""Named multi-step routines (macros). Define in config.ROUTINES."""
from .. import config
from . import system, web


def run_routine(name: str) -> str:
    name = name.strip().lower()
    steps = config.ROUTINES.get(name)
    if not steps:
        return f"No routine named '{name}'. Known: {', '.join(config.ROUTINES)}"
    done = []
    for step in steps:
        action = step.get("action")
        if action == "open_app":
            system.open_app(step["name"])
            done.append(f"opened {step['name']}")
        elif action == "open_url":
            web.open_url(step["url"])
            done.append(f"opened {step['url']}")
        elif action == "say":
            done.append(step["text"])
    return f"Running {name}: " + "; ".join(done)


def list_routines() -> str:
    return "Routines: " + ", ".join(config.ROUTINES) if config.ROUTINES else "No routines defined."


SKILLS = [
    ({"name": "run_routine",
      "description": "Run a named routine/macro (e.g. 'good morning', 'work', 'shutdown').",
      "parameters": {"type": "object",
                     "properties": {"name": {"type": "string"}}, "required": ["name"]}}, run_routine),
    ({"name": "list_routines", "description": "List available routines.",
      "parameters": {"type": "object", "properties": {}}}, list_routines),
]
