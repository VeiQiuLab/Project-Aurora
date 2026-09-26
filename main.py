"""Official Aurora Desktop entrypoint. No Tk or Python AI initialization."""
from modules.desktop_launcher import main


if __name__ == "__main__":
    raise SystemExit(main())
