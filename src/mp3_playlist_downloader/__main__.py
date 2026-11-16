"""GUI entry point and offline diagnostics CLI."""

import argparse

from . import __version__


def main() -> int:
    parser = argparse.ArgumentParser(prog="mp3-playlist-downloader")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("doctor").add_argument("--json", action="store_true")
    commands.add_parser("demo").add_argument("--check", action="store_true")
    commands.add_parser("version")
    args = parser.parse_args()
    if args.command == "version":
        print(__version__)
        return 0
    if args.command == "doctor":
        from .cli import print_doctor
        return print_doctor(args.json)
    if args.command == "demo":
        from .demo import run
        return run(args.check)
    from .app import run
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
