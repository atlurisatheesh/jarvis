"""Universal skills — make JARVIS general-purpose, not limited to coded tools.

run_command + press_hotkey + type_text (in system) together let it operate
ANY Windows app or task, plus calculate for instant math. The brain answers
general knowledge questions on its own without any tool.
"""
import ast
import operator
import subprocess

from .. import config

# ---- safe arithmetic evaluator (no eval of arbitrary code) ----
_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv, ast.USub: operator.neg, ast.UAdd: operator.pos,
}


def _eval(node):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.BinOp):
        return _OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp):
        return _OPS[type(node.op)](_eval(node.operand))
    raise ValueError("unsupported expression")


def calculate(expression: str) -> str:
    try:
        result = _eval(ast.parse(expression, mode="eval").body)
        return f"{expression} = {result}"
    except Exception:
        return "Could not compute that expression."


def run_command(command: str) -> str:
    """Run an arbitrary PowerShell command on the laptop (this is your own PC)."""
    if not config.ALLOW_SHELL:
        return "Shell commands are disabled (set ALLOW_SHELL=True in config)."
    print(f"[shell] {command}")
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True, text=True, timeout=120,
        )
        out = (r.stdout or r.stderr or "done").strip()
        return out[:1200] if out else "Command finished."
    except Exception as e:
        return f"Command error: {e}"


def press_hotkey(keys: str) -> str:
    """Press a keyboard shortcut, keys separated by '+', e.g. 'ctrl+s' or 'alt+tab'."""
    import pyautogui
    combo = [k.strip().lower() for k in keys.split("+") if k.strip()]
    if not combo:
        return "No keys given."
    pyautogui.hotkey(*combo)
    return f"Pressed {keys}."


SKILLS = [
    ({"name": "calculate", "description": "Evaluate an arithmetic expression (+ - * / ** % //).",
      "parameters": {"type": "object",
                     "properties": {"expression": {"type": "string"}}, "required": ["expression"]}}, calculate),
    ({"name": "run_command",
      "description": "Run any PowerShell command on the laptop to do tasks no other tool covers.",
      "parameters": {"type": "object",
                     "properties": {"command": {"type": "string"}}, "required": ["command"]}}, run_command),
    ({"name": "press_hotkey",
      "description": "Press a keyboard shortcut to control any app (e.g. 'ctrl+s', 'alt+f4', 'win+e').",
      "parameters": {"type": "object",
                     "properties": {"keys": {"type": "string"}}, "required": ["keys"]}}, press_hotkey),
]
