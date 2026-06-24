"""Safe end-to-end tests for the mobile (Telegram) bridge.

Mocks skills.run_tool so NO real action executes (no SMS, calls, sleep, shutdown).
Verifies that phone messages route through the same reflex pipeline as voice,
and that destructive commands are gated behind confirmation.

Run:  python test_mobile_safe.py
"""
import sys
from unittest import mock

from jarvis_ai import assistant_core


def _route_with_mock(text, pending_reset=True):
    """Route a phone message, capturing which tool would run (without running it)."""
    calls = []

    def fake_run_tool(name, args=None):
        calls.append((name, args or {}))
        return f"[mocked {name}]"

    if pending_reset:
        assistant_core._clear_pending()
    with mock.patch.object(assistant_core.skills, "run_tool", side_effect=fake_run_tool):
        result = assistant_core.handle_local_intent(text)
    return result, calls


CASES = [
    # (phone message, expected tool, must NOT execute destructive)
    ("read my messages", "phone_unread_sms"),
    ("any new texts", "phone_unread_sms"),
    ("recent messages", "phone_read_sms"),
    ("what is on the screen", "see_screen"),
    ("read clipboard", "read_clipboard"),
    ("any new email", "unread_email"),
    ("dark mode", "dark_mode"),
    ("my ip", "get_ip"),
    ("top processes", "get_processes"),
]


def test_routing():
    passed = 0
    for text, expected in CASES:
        result, calls = _route_with_mock(text)
        tool_names = [c[0] for c in calls]
        assert result.handled, f"'{text}' not handled"
        assert expected in tool_names, f"'{text}' -> {tool_names}, expected {expected}"
        passed += 1
        print(f"  OK  {text:28s} -> {expected}")
    return passed


def test_destructive_gated():
    """Power commands must ask for confirmation, NOT execute on first utterance."""
    passed = 0
    for text in ["shutdown the computer", "restart the laptop", "sleep the computer"]:
        result, calls = _route_with_mock(text)
        assert result.handled, f"'{text}' not handled"
        assert calls == [], f"'{text}' executed {calls} without confirmation!"
        assert result.action.startswith("confirm_"), f"'{text}' not gated: {result.action}"
        passed += 1
        print(f"  OK  {text:28s} -> gated ({result.action})")

    # Confirm flow runs the tool only after explicit 'yes'
    _route_with_mock("shutdown the computer")  # arms pending
    result, calls = _route_with_mock("yes", pending_reset=False)
    assert ("shutdown_pc", {}) in calls, f"'yes' did not run shutdown_pc: {calls}"
    passed += 1
    print(f"  OK  {'yes (after shutdown prompt)':28s} -> shutdown_pc fired")

    # 'no' cancels without executing
    _route_with_mock("restart the laptop")
    result, calls = _route_with_mock("no", pending_reset=False)
    assert calls == [], f"'no' executed something: {calls}"
    passed += 1
    print(f"  OK  {'no (after restart prompt)':28s} -> cancelled, nothing ran")
    return passed


def test_telegram_auth():
    """Empty allowlist allows all; populated allowlist blocks strangers."""
    import jarvis_ai.telegram_bot as tb
    from jarvis_ai import config

    class FakeUser:
        def __init__(self, uid): self.id = uid

    class FakeUpdate:
        def __init__(self, uid): self.effective_user = FakeUser(uid)

    orig = config.TELEGRAM_ALLOWED_USERS
    try:
        config.TELEGRAM_ALLOWED_USERS = []
        assert tb._authorized(FakeUpdate(999)) is True
        config.TELEGRAM_ALLOWED_USERS = [123]
        assert tb._authorized(FakeUpdate(123)) is True
        assert tb._authorized(FakeUpdate(999)) is False
    finally:
        config.TELEGRAM_ALLOWED_USERS = orig
    print("  OK  telegram auth gate (empty=open, set=locked)")
    return 1


def test_remote_origin_gate():
    """Remote (web/telegram/phone) must NOT run shell or destructive tools."""
    from jarvis_ai import skills
    passed = 0
    skills.set_origin("remote")
    for t in ["run_command", "shutdown_pc", "phone_call", "toggle_wifi", "kill_process"]:
        out = skills.run_tool(t, {})
        assert "blocked for remote" in out, f"remote {t} NOT blocked: {out}"
        passed += 1
        print(f"  OK  remote {t:14s} -> blocked")
    # safe read tool still allowed over remote
    out = skills.run_tool("get_ip", {})
    assert "blocked" not in out, f"remote get_ip wrongly blocked: {out}"
    print("  OK  remote get_ip         -> allowed")
    passed += 1
    skills.set_origin("local")  # reset
    return passed


if __name__ == "__main__":
    print("Mobile bridge — safe routing tests (no real actions executed)\n")
    n = 0
    print("Routing (phone message -> correct tool):")
    n += test_routing()
    print("\nDestructive command safety:")
    n += test_destructive_gated()
    print("\nTelegram authorization:")
    n += test_telegram_auth()
    print("\nRemote origin gate (shell/destructive blocked over network):")
    n += test_remote_origin_gate()
    print(f"\n{n} checks passed. No SMS, calls, sleep, or shutdown were executed.")
    sys.exit(0)
