from jarvis_ai.brain import _clean_provider_reply


def test_provider_reply_does_not_speak_function_markup():
    raw = 'Sure, Sir.\n<function=run_command[]>{"command":"sleep"}</function>'

    assert _clean_provider_reply(raw) == "Sure, Sir."


def test_provider_reply_does_not_speak_tool_call_markup():
    raw = '<tool_call>{"name":"run_command","arguments":{"command":"shutdown"}}</tool_call>'

    assert _clean_provider_reply(raw) == "I heard you, Sir."
