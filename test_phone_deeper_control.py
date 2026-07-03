from unittest.mock import patch


def test_phone_maps_opens_navigation_intent():
    from jarvis_ai.skills import phone

    calls = []

    def fake_adb(*args, timeout=20):
        calls.append(args)
        return ""

    with patch.object(phone, "_adb", side_effect=fake_adb):
        result = phone.phone_maps("home")

    assert result == "Opening navigation to home on the phone."
    assert ("shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", "google.navigation:q=home") in calls


def test_phone_youtube_search_opens_search_url():
    from jarvis_ai.skills import phone

    calls = []

    def fake_adb(*args, timeout=20):
        calls.append(args)
        return ""

    with patch.object(phone, "_adb", side_effect=fake_adb):
        result = phone.phone_youtube_search("ilayaraja telugu")

    assert "Opening https://www.youtube.com/results?search_query=ilayaraja+telugu" in result
    assert calls[0][:5] == ("shell", "am", "start", "-a", "android.intent.action.VIEW")


def test_phone_screen_dump_parses_ui_text():
    from jarvis_ai.skills import phone

    xml = """
    <hierarchy>
      <node text="YouTube" content-desc="" bounds="[0,0][100,80]" clickable="true" />
      <node text="" content-desc="Search" bounds="[100,0][200,80]" clickable="true" />
    </hierarchy>
    """

    def fake_adb(*args, timeout=20):
        if args[:2] == ("shell", "cat"):
            return xml
        return "ok"

    with patch.object(phone, "_adb", side_effect=fake_adb):
        result = phone.phone_screen_dump()

    assert "YouTube [0,0][100,80] clickable" in result
    assert "Search [100,0][200,80] clickable" in result


def test_phone_tap_text_taps_center_of_matching_node():
    from jarvis_ai.skills import phone

    xml = '<hierarchy><node text="Allow" content-desc="" bounds="[10,20][110,120]" clickable="true" /></hierarchy>'
    calls = []

    def fake_adb(*args, timeout=20):
        calls.append(args)
        if args[:2] == ("shell", "cat"):
            return xml
        return "ok"

    with patch.object(phone, "_adb", side_effect=fake_adb):
        result = phone.phone_tap_text("allow")

    assert result == "Tapped allow on the phone."
    assert ("shell", "input", "tap", "60", "70") in calls


def test_assistant_confirms_phone_sms_before_drafting():
    from jarvis_ai.assistant_session import AssistantSession

    session = AssistantSession(followup_seconds=0)
    first = session.handle("Leha send sms to 12345 saying hello there", lambda text: "brain")
    assert "Say yes" in first.reply

    with patch("jarvis_ai.skills.run_tool", return_value="SMS drafted.") as run_tool:
        second = session.handle("Leha yes", lambda text: "brain")

    assert second.reply == "SMS drafted."
    run_tool.assert_called_once_with(
        "phone_send_sms",
        {"number": "12345", "message": "hello there"},
    )


def test_assistant_opens_spoken_domain_on_phone_as_url():
    from jarvis_ai.assistant_session import AssistantSession

    with patch("jarvis_ai.skills.run_tool", return_value="Opening https://google.com on the phone.") as run_tool:
        result = AssistantSession(followup_seconds=0).handle(
            "Leha open google.com on my phone",
            lambda text: "brain",
        )

    assert result.reply == "Opening https://google.com on the phone."
    run_tool.assert_called_once_with("phone_open_url", {"url": "google.com"})


def test_assistant_routes_phone_navigation_to_phone_maps():
    from jarvis_ai.assistant_session import AssistantSession

    with patch("jarvis_ai.skills.run_tool", return_value="Opening navigation to hyderabad on the phone.") as run_tool:
        result = AssistantSession(followup_seconds=0).handle(
            "Leha navigate to hyderabad on my phone",
            lambda text: "brain",
        )

    assert result.reply == "Opening navigation to hyderabad on the phone."
    run_tool.assert_called_once_with("phone_maps", {"destination": "hyderabad"})
