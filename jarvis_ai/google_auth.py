"""Run once to connect Leha to the user's Google account."""
from .skills.google import authorize_google


def main():
    print(authorize_google())


if __name__ == "__main__":
    main()
