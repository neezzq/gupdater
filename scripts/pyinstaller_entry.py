"""Entry point used by PyInstaller to build GUpdater.exe."""

from gupdater.app import main

if __name__ == "__main__":
    raise SystemExit(main())
