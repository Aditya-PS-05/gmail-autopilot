"""Thin CLI wrapper around `api.run_autopilot`.

Usage:
    python -m gmail_autopilot                              # dry-run with mock+fake
    python -m gmail_autopilot --mode real
    python -m gmail_autopilot --gmail real --llm anthropic
    python -m gmail_autopilot --inspect run_abc123def012   # show a stored run
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
        prog="gmail-autopilot",
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
        help="instead of running, print a stored run's JSON record",
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
    cfg = Config.from_env(**overrides)

    if args.inspect:
        from .state.repository import Repository

        repo = Repository(cfg.db_path)
        try:
            row = repo.get_run(args.inspect)
            if not row:
                print(f"no run found: {args.inspect}", file=sys.stderr)
                return 1
            print(json.dumps(row, indent=2, default=str))
            return 0
        finally:
            repo.close()

    run = run_autopilot(cfg)
    print(run.model_dump_json(indent=2))
    s = run.summary
    print(
        f"\nrun {run.id}  mode={run.mode.value}  duration={run.duration_ms}ms  status={run.status}",
        file=sys.stderr,
    )
    if s:
        print(
            f"  fetched={s.fetched}  needs_reply={s.needs_reply}  "
            f"skipped_no_reply={s.skipped_no_reply}  drafts_generated={s.drafts_generated}  "
            f"drafts_created={s.drafts_created}  failed={s.failed}",
            file=sys.stderr,
        )
    return 0 if run.status in ("completed",) else 1


if __name__ == "__main__":
    sys.exit(main())
