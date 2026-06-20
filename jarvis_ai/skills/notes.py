"""Memory skills: let the user tell JARVIS facts to remember."""
from .. import memory


def remember_fact(fact: str) -> str:
    return memory.remember(fact)


def recall_facts() -> str:
    facts = memory.all_facts()
    return "I remember: " + "; ".join(facts) if facts else "I have no saved notes yet."


SKILLS = [
    ({"name": "remember_fact",
      "description": "Save a fact about the user for future sessions (preferences, names, routines).",
      "parameters": {"type": "object",
                     "properties": {"fact": {"type": "string"}}, "required": ["fact"]}}, remember_fact),
    ({"name": "recall_facts", "description": "List everything currently remembered about the user.",
      "parameters": {"type": "object", "properties": {}}}, recall_facts),
]
