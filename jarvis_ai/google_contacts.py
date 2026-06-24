"""Enhanced Google Contacts operations.

    - Search contacts by name (read)
    - Get contact details (email, phone) for confirmed workflows (read)
    - Resolve a name to a phone number for call/SMS confirmation
"""
from __future__ import annotations

from .google_services import get_service, _check_rate


def search(query: str) -> str:
    """Search contacts by name."""
    if not _check_rate("contacts"):
        return "Contacts rate limit reached."
    service = get_service("people", "v1")
    people = (
        service.people()
        .searchContacts(query=query, readMask="names,emailAddresses,phoneNumbers", pageSize=5)
        .execute()
        .get("results", [])
    )
    if not people:
        return f"No contacts matching {query}."
    names = [
        r.get("person", {}).get("names", [{}])[0].get("displayName", "Unknown")
        for r in people
    ]
    return "Contacts: " + "; ".join(names)


def get_details(query: str) -> dict:
    """Get full contact details (name, email, phone) for the best match."""
    if not _check_rate("contacts"):
        return {}
    service = get_service("people", "v1")
    people = (
        service.people()
        .searchContacts(query=query, readMask="names,emailAddresses,phoneNumbers", pageSize=1)
        .execute()
        .get("results", [])
    )
    if not people:
        return {}
    person = people[0].get("person", {})
    name = person.get("names", [{}])[0].get("displayName", "Unknown")
    emails = [e.get("value", "") for e in person.get("emailAddresses", [])]
    phones = [p.get("value", "") for p in person.get("phoneNumbers", [])]
    return {"name": name, "emails": emails, "phones": phones}


def resolve_phone(query: str) -> str:
    """Resolve a contact name to a phone number for call/SMS workflows."""
    details = get_details(query)
    if not details:
        return f"No contact named {query}, Sir."
    phones = details.get("phones", [])
    if not phones:
        return f"{details.get('name', query)} has no phone number, Sir."
    return phones[0]


def resolve_email(query: str) -> str:
    """Resolve a contact name to an email address."""
    details = get_details(query)
    if not details:
        return f"No contact named {query}, Sir."
    emails = details.get("emails", [])
    if not emails:
        return f"{details.get('name', query)} has no email, Sir."
    return emails[0]
