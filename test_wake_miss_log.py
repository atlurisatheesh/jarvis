from pathlib import Path

from jarvis_ai import config, wake_miss_log


def test_wake_miss_log_records_and_suggests(tmp_path):
    old = config.WAKE_MISS_LOG
    config.WAKE_MISS_LOG = str(tmp_path / "wake_misses.jsonl")
    try:
        wake_miss_log.log_miss("Levaa open maps", 0.81)
        wake_miss_log.log_miss("Levaa what time", 0.79)
        wake_miss_log.log_miss("later open maps", 0.95)

        rows = wake_miss_log.load_recent()
        assert len(rows) == 3

        suggestions = wake_miss_log.suggest_variants(min_confidence=0.5, min_count=2)
        assert suggestions
        assert suggestions[0]["candidate"] == "levaa"
        assert suggestions[0]["count"] == 2
        assert all(s["candidate"] != "later" for s in suggestions)
    finally:
        config.WAKE_MISS_LOG = old


def test_wake_miss_status_without_file(tmp_path):
    old = config.WAKE_MISS_LOG
    config.WAKE_MISS_LOG = str(tmp_path / "missing.jsonl")
    try:
        status = wake_miss_log.status()
        assert status["miss_count"] == 0
        assert status["suggestions"] == []
        assert Path(status["path"]).name == "missing.jsonl"
    finally:
        config.WAKE_MISS_LOG = old
