"""Keep automated brain tests out of Leha's daily conversation memory."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_persistent_conversation(tmp_path, monkeypatch):
    from jarvis_ai import conversation_store

    monkeypatch.setattr(conversation_store, "_STORE", tmp_path / "conversation.json")
