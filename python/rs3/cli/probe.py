"""CLI entry point for the RS3 protocol probe tool."""

from __future__ import annotations

from ..tools.probe import build_parser, main, on_notify, parse_args, run_probe, run_sequence

__all__ = ["build_parser", "main", "on_notify", "parse_args", "run_probe", "run_sequence"]


if __name__ == "__main__":
    main()
