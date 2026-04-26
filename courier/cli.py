"""CLI entry point.

Default behavior:
    - TTY:    rich-formatted live UI on stdout, errors only to stderr.
    - Pipe:   raw JSON `AutoPilotRun` on stdout (auto-detect, or --json).

Flags:
    --mode dry-run|real        override BRACE_MODE
    --limit N                  override BRACE_LIMIT
    --gmail mock|real          override BRACE_GMAIL_BACKEND
    --llm fake|anthropic|openai|grok|auto
    --db PATH                  sqlite path
    --inspect RUN_ID           print a stored run record and exit
    --json                     force JSON output (skip rich UI)
    -q, --quiet                hide per-email progress; show only summary
    -v, --verbose              also emit structured logs to stderr
    --no-color                 disable color output (also via NO_COLOR env)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .api import run_autopilot
from .config import Config
from .models import Mode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="courier",
        description="Run the AutoPilot inbox workflow. Produces drafts; never sends.",
    )
    parser.add_argument(
        "--mode",
        choices=["dry-run", "real"],
        default=None,
        help="dry-run generates drafts but does NOT create them in Gmail",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--gmail", choices=["mock", "real"], default=None)
    parser.add_argument(
        "--llm",
        choices=["fake", "anthropic", "openai", "grok", "auto"],
        default=None,
        help="auto: route per-task across whichever provider keys are configured",
    )
    parser.add_argument("--db", default=None, help="sqlite path (default runs.db)")
    parser.add_argument(
        "--inspect",
        metavar="RUN_ID",
        help="instead of running, print a stored run's record and exit",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit a JSON document on stdout (no interactive UI)",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="hide per-email progress; show only the final summary",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="also emit structured JSON logs to stderr",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="disable ANSI color (also respects NO_COLOR env var)",
    )
    parser.add_argument(
        "--no-review",
        action="store_true",
        help="skip the post-run prompt to review/edit drafts (for non-interactive use)",
    )
    args = parser.parse_args(argv)

    overrides: dict = {}
    if args.mode:
        overrides["mode"] = Mode(args.mode)
    if args.limit is not None:
        overrides["limit"] = args.limit
    if args.gmail:
        overrides["gmail_backend"] = args.gmail
    if args.llm:
        overrides["llm_backend"] = args.llm
    if args.db:
        overrides["db_path"] = Path(args.db)
    # Quiet by default; --verbose surfaces all the workflow logs.
    overrides["log_level"] = "INFO" if args.verbose else "WARNING"
    cfg = Config.from_env(**overrides)

    # Pipe-aware output mode: TTY → pretty, otherwise → JSON.
    use_json = args.json or not sys.stdout.isatty()

    # Inspect path
    if args.inspect:
        return _do_inspect(cfg, args.inspect, use_json=use_json, no_color=args.no_color)

    # Run path
    if use_json:
        run = run_autopilot(cfg)
        print(run.model_dump_json(indent=2))
    else:
        from rich.console import Console

        from .api import _build_gmail, _build_llm
        from .cli_ui import CliUI

        console = Console(no_color=args.no_color)
        ui = CliUI(console, show_per_email=not args.quiet)
        # Build gmail explicitly so the post-run review can reuse the same client.
        gmail = _build_gmail(cfg)
        llm = _build_llm(cfg)
        run = run_autopilot(cfg, gmail=gmail, llm=llm, on_progress=ui)

        # Optional post-run review TUI: only when interactive, not piped, real
        # mode, and at least one draft was created.
        if (
            not args.no_review
            and sys.stdin.isatty()
            and run.mode.value == "real"
            and any(b.draft_id for b in run.action_briefs)
        ):
            from .cli_review import review_drafts

            review_drafts(run.action_briefs, gmail, console)

    return 0 if run.status == "completed" else 1


def _do_inspect(cfg: Config, run_id: str, *, use_json: bool, no_color: bool) -> int:
    from .state.repository import Repository

    repo = Repository(cfg.db_path)
    try:
        row = repo.get_run(run_id)
        if not row:
            print(f"no run found: {run_id}", file=sys.stderr)
            return 1
        if use_json:
            print(json.dumps(row, indent=2, default=str))
        else:
            from rich.console import Console

            from .cli_ui import render_inspected_row

            console = Console(no_color=no_color)
            render_inspected_row(row, console)
        return 0
    finally:
        repo.close()


if __name__ == "__main__":
    sys.exit(main())
