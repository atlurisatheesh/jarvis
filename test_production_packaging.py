from pathlib import Path


ROOT = Path(__file__).resolve().parent


def test_production_scripts_exist():
    expected = [
        "scripts/install_production.ps1",
        "scripts/build_android_debug.ps1",
        "scripts/validate_startup.ps1",
        "scripts/cleanup_logs.ps1",
        "scripts/start_leha.ps1",
        "scripts/stop_leha.ps1",
        "scripts/status_leha.ps1",
        "scripts/start_tray.ps1",
        "Start Leha Production.bat",
    ]
    for rel in expected:
        assert (ROOT / rel).exists(), rel


def test_start_script_manages_dashboard_server():
    text = (ROOT / "scripts/start_leha.ps1").read_text(encoding="utf-8")
    assert "jarvis_ai.supervisor" in text
    assert "jarvis_ai.webserver" in text


def test_production_scripts_do_not_power_cycle_machine():
    forbidden = ["shutdown.exe", "Restart-Computer", "Stop-Computer", "rundll32.exe powrprof"]
    for path in (ROOT / "scripts").glob("*.ps1"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for bad in forbidden:
            assert bad.lower() not in text.lower(), f"{bad} found in {path}"
