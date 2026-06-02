"""Run SEPCC entry points without locking Windows console-script shims."""

from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run SEPCC Windows launcher entry points through Python."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("check", help="Import launcher modules.")
    subparsers.add_parser("serve", help="Start the SEPCC server.")
    bootstrap = subparsers.add_parser("bootstrap", help="Run context bootstrap.")
    bootstrap.add_argument("--target", required=True)
    launch = subparsers.add_parser("launch", help="Launch Claude Code through SEPCC.")
    launch.add_argument("project")
    args = parser.parse_args()

    if args.command == "check":
        import cli.bootstrap_context
        import cli.entrypoints

        assert cli.bootstrap_context is not None
        assert cli.entrypoints is not None
        return

    if args.command == "serve":
        from cli.entrypoints import serve

        serve()
        return

    if args.command == "bootstrap":
        from cli.bootstrap_context import main as bootstrap_main

        bootstrap_main(["--target", args.target])
        return

    if args.command == "launch":
        from cli.entrypoints import launch_claude

        launch_claude([args.project])
        return

    raise SystemExit(f"unknown command: {args.command}")


if __name__ == "__main__":
    main()
