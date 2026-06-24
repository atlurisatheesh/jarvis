"""Keep Leha's listener alive: restart on crash, log everything.

    python -m jarvis_ai.supervisor
    python -m jarvis_ai.supervisor --check    # report health, do not launch

Runs ``python -m jarvis_ai.listen`` and relaunches it if it exits. Caps the
restart rate so a hard crash loop doesn't spin the CPU. Logs are written through
:mod:`jarvis_ai.log_manager` (token-redacted, rotated, retention-bounded) to
``logs/leha.log``. Use this as the target of a Windows startup task
(see ``scripts/install_autostart.ps1``).
"""
import subprocess
import sys
import time

from . import config
from . import log_manager

_LOG = log_manager.log


def _startup_housekeeping() -> None:
    """Trim logs older than the retention window before launching the loop."""
    try:
        removed = log_manager.cleanup_old_logs()
        if removed:
            _LOG(f"startup cleanup removed {removed} old log file(s)", component="supervisor")
    except Exception as e:
        _LOG(f"startup cleanup failed: {e}", component="supervisor", level="WARN")


def health_check() -> int:
    """Print a one-shot health summary and return a process exit code.

    0 = healthy, non-zero = at least one subsystem failed. Used by ``--check``
    and by external monitors (Task Scheduler, Home Assistant, etc.).
    """
    _LOG("running --check health probe", component="supervisor")
    try:
        from . import health
        print(health.summary())
        status = health.check()
        failed = [name for name, ok in status.items() if not ok]
        if failed:
            print(f"[supervisor] check FAILED: {', '.join(failed)}")
            return 1
        print("[supervisor] check OK")
        return 0
    except Exception as e:
        print(f"[supervisor] check error: {e}")
        return 2


def main():
    args = sys.argv[1:]
    if "--check" in args:
        return sys.exit(health_check())

    _LOG("starting Leha listener supervisor", component="supervisor")
    _startup_housekeeping()
    restarts = []  # timestamps of recent restarts
    while True:
        start = time.time()
        _LOG("launching listener", component="supervisor")
        try:
            proc = subprocess.run([sys.executable, "-u", "-m", "jarvis_ai.listen"])
            code = proc.returncode
        except KeyboardInterrupt:
            _LOG("stopped by user", component="supervisor")
            return
        except Exception as e:
            _LOG(f"launch error: {e}", component="supervisor", level="ERROR")
            code = -1

        ran = time.time() - start
        _LOG(f"listener exited (code={code}) after {ran:.0f}s", component="supervisor")

        # crash-loop guard: if >3 restarts in 60s, back off 30s
        now = time.time()
        restarts = [t for t in restarts if now - t < 60]
        restarts.append(now)
        if len(restarts) > 3:
            _LOG("too many restarts; backing off 30s", component="supervisor", level="WARN")
            time.sleep(30)
            restarts = []
        else:
            time.sleep(2)


if __name__ == "__main__":
    main()
