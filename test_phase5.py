"""Tests for Phase 5: Google productivity (calendar, gmail, drive, contacts).

All tests mock the Google API responses — no real network calls.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Google services layer
# ---------------------------------------------------------------------------

class TestGoogleServices(unittest.TestCase):
    """Tests for jarvis_ai.google_services."""

    def test_google_scopes_defined(self):
        from jarvis_ai.google_services import GOOGLE_SCOPES
        self.assertGreater(len(GOOGLE_SCOPES), 5)
        self.assertIn("openid", GOOGLE_SCOPES)

    def test_rate_limiting_allows_under_limit(self):
        from jarvis_ai.google_services import _check_rate, _rate_log
        _rate_log.clear()
        for _ in range(5):
            self.assertTrue(_check_rate("test_api"))

    def test_rate_limiting_blocks_over_limit(self):
        from jarvis_ai.google_services import _check_rate, _rate_log, _rate_limit_per_min
        _rate_log.clear()
        # Simulate hitting the limit
        for _ in range(_rate_limit_per_min):
            _check_rate("blocked_api")
        self.assertFalse(_check_rate("blocked_api"))

    def test_rate_status(self):
        from jarvis_ai.google_services import _check_rate, _rate_log, rate_status
        _rate_log.clear()
        _check_rate("status_api")
        status = rate_status()
        self.assertIn("status_api", status)


# ---------------------------------------------------------------------------
# Google Calendar
# ---------------------------------------------------------------------------

class TestGoogleCalendar(unittest.TestCase):
    """Tests for jarvis_ai.google_calendar."""

    def test_create_preview_with_valid_date(self):
        from jarvis_ai.google_calendar import create_preview
        result = create_preview("Meeting", "2026-06-24T15:00", 60)
        self.assertIn("Ready to add 'Meeting'", result)
        self.assertIn("confirm", result)

    def test_create_preview_invalid_date(self):
        from jarvis_ai.google_calendar import create_preview
        result = create_preview("Meeting", "invalid-date")
        self.assertIn("Give a start time", result)

    def test_search_by_date_invalid_format(self):
        from jarvis_ai.google_calendar import search_by_date
        result = search_by_date("not-a-date")
        self.assertIn("Invalid start date", result)


# ---------------------------------------------------------------------------
# Google Gmail
# ---------------------------------------------------------------------------

class TestGoogleGmail(unittest.TestCase):
    """Tests for jarvis_ai.google_gmail."""

    def test_compose_preview(self):
        from jarvis_ai.google_gmail import compose_preview
        result = compose_preview("mom@example.com", "Hello", "Hi Mom!")
        self.assertIn("Ready to send to mom@example.com", result)
        self.assertIn("confirm", result)

    def test_compose_preview_missing_recipient(self):
        from jarvis_ai.google_gmail import compose_preview
        result = compose_preview("", "Hello", "Hi!")
        self.assertIn("Who should I send it to", result)

    def test_extract_body_from_simple_message(self):
        import base64
        from jarvis_ai.google_gmail import _extract_body
        body_text = "Hello, this is the email body."
        encoded = base64.urlsafe_b64encode(body_text.encode()).decode()
        msg = {"payload": {"body": {"data": encoded}}}
        result = _extract_body(msg)
        self.assertEqual(result, body_text)

    def test_extract_body_from_multipart(self):
        import base64
        from jarvis_ai.google_gmail import _extract_body
        body_text = "Multipart body text."
        encoded = base64.urlsafe_b64encode(body_text.encode()).decode()
        msg = {
            "payload": {
                "parts": [
                    {"mimeType": "text/plain", "body": {"data": encoded}},
                    {"mimeType": "text/html", "body": {"data": "abc"}},
                ]
            }
        }
        result = _extract_body(msg)
        self.assertEqual(result, body_text)

    def test_extract_headers(self):
        from jarvis_ai.google_gmail import _extract_headers
        msg = {
            "payload": {
                "headers": [
                    {"name": "From", "value": "sender@example.com"},
                    {"name": "Subject", "value": "Test Subject"},
                ]
            }
        }
        headers = _extract_headers(msg)
        self.assertEqual(headers["from"], "sender@example.com")
        self.assertEqual(headers["subject"], "Test Subject")


# ---------------------------------------------------------------------------
# Google Drive
# ---------------------------------------------------------------------------

class TestGoogleDrive(unittest.TestCase):
    """Tests for jarvis_ai.google_drive."""

    @patch("jarvis_ai.google_drive.get_service")
    def test_search_returns_names(self, mock_get_service):
        from jarvis_ai.google_drive import search
        mock_service = MagicMock()
        mock_service.files().list().execute.return_value = {
            "files": [
                {"id": "1", "name": "Doc1.pdf"},
                {"id": "2", "name": "Doc2.docx"},
            ]
        }
        mock_get_service.return_value = mock_service
        result = search("Doc")
        self.assertIn("Doc1.pdf", result)
        self.assertIn("Doc2.docx", result)

    @patch("jarvis_ai.google_drive.get_service")
    def test_search_no_results(self, mock_get_service):
        from jarvis_ai.google_drive import search
        mock_service = MagicMock()
        mock_service.files().list().execute.return_value = {"files": []}
        mock_get_service.return_value = mock_service
        result = search("nonexistent")
        self.assertIn("No Drive files", result)


# ---------------------------------------------------------------------------
# Google Contacts
# ---------------------------------------------------------------------------

class TestGoogleContacts(unittest.TestCase):
    """Tests for jarvis_ai.google_contacts."""

    @patch("jarvis_ai.google_contacts.get_service")
    def test_search_returns_names(self, mock_get_service):
        from jarvis_ai.google_contacts import search
        mock_service = MagicMock()
        mock_service.people().searchContacts().execute.return_value = {
            "results": [
                {"person": {"names": [{"displayName": "Mom"}]}},
                {"person": {"names": [{"displayName": "Dad"}]}},
            ]
        }
        mock_get_service.return_value = mock_service
        result = search("Mom")
        self.assertIn("Mom", result)

    @patch("jarvis_ai.google_contacts.get_service")
    def test_get_details_returns_full_info(self, mock_get_service):
        from jarvis_ai.google_contacts import get_details
        mock_service = MagicMock()
        mock_service.people().searchContacts().execute.return_value = {
            "results": [{
                "person": {
                    "names": [{"displayName": "Mom"}],
                    "emailAddresses": [{"value": "mom@example.com"}],
                    "phoneNumbers": [{"value": "+1234567890"}],
                }
            }]
        }
        mock_get_service.return_value = mock_service
        details = get_details("Mom")
        self.assertEqual(details["name"], "Mom")
        self.assertIn("mom@example.com", details["emails"])
        self.assertIn("+1234567890", details["phones"])

    @patch("jarvis_ai.google_contacts.get_service")
    def test_get_details_no_results(self, mock_get_service):
        from jarvis_ai.google_contacts import get_details
        mock_service = MagicMock()
        mock_service.people().searchContacts().execute.return_value = {"results": []}
        mock_get_service.return_value = mock_service
        details = get_details("Unknown Person")
        self.assertEqual(details, {})

    @patch("jarvis_ai.google_contacts.get_details")
    def test_resolve_phone_found(self, mock_get_details):
        from jarvis_ai.google_contacts import resolve_phone
        mock_get_details.return_value = {"name": "Mom", "phones": ["+1234567890"]}
        result = resolve_phone("Mom")
        self.assertEqual(result, "+1234567890")

    @patch("jarvis_ai.google_contacts.get_details")
    def test_resolve_phone_no_phone(self, mock_get_details):
        from jarvis_ai.google_contacts import resolve_phone
        mock_get_details.return_value = {"name": "Mom", "phones": []}
        result = resolve_phone("Mom")
        self.assertIn("no phone", result)


# ---------------------------------------------------------------------------
# Skills registration (verify new skills are registered)
# ---------------------------------------------------------------------------

class TestGoogleSkillsRegistration(unittest.TestCase):
    """Tests for the updated skills/google.py module."""

    def test_new_skills_registered(self):
        from jarvis_ai.skills.google import SKILLS
        names = [s[0]["name"] for s in SKILLS]
        # Phase 5 new skills
        self.assertIn("google_calendar_search", names)
        self.assertIn("google_gmail_read", names)
        self.assertIn("google_drive_read", names)
        self.assertIn("google_drive_recent", names)
        self.assertIn("google_contacts_get", names)
        # Original skills still present
        self.assertIn("google_calendar_upcoming", names)
        self.assertIn("google_gmail_search", names)
        self.assertIn("google_gmail_send", names)
        self.assertIn("open_google_maps", names)


if __name__ == "__main__":
    unittest.main(verbosity=2)
