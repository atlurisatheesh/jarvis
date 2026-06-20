"""Compatibility entry point.

The original ``main`` used openwakeword, which is unreliable on this machine.
The maintained always-on voice loop lives in ``jarvis_ai.listen``.
"""


def main():
    from .listen import main as listen_main

    listen_main()


if __name__ == "__main__":
    main()
