"""Rich-based renderer for the interactive CLI experience.

Used only when stdout is a TTY and `--json` is not set. Subscribes to
WorkflowRunner progress events and prints a live-updating per-email feed plus
a final summary table.

In pipe / --json mode, this module is not used."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from .engine.events import (
    EmailCompleted,
    EmailsFetched,
    ProgressEvent,
    RunFinished,
    RunStarted,
)

_STATUS_GLYPH = {
    "replied_draft_created": "[bold green]✓[/]",
    "replied_dry_run": "[bold cyan]≣[/]",
    "skipped_no_reply_needed": "[dim]⊘[/]",
    "failed": "[bold red]✗[/]",
}

_STATUS_NOTE = {
    "replied_draft_created": "draft created",
    "replied_dry_run": "draft generated [dim](dry-run)[/]",
    "skipped_no_reply_needed": "[dim]no reply needed[/]",
    "failed": "[red]failed[/]",
}


class CliUI:
    """A subscriber for ProgressEvents that paints a pretty terminal UI."""

    def __init__(self, console: Console | None = None, *, show_per_email: bool = True):
        self.console = console or Console()
        self.show_per_email = show_per_email
        self._total = 0

    def __call__(self, event: ProgressEvent) -> None:
        if isinstance(event, RunStarted):
            self._render_start(event)
        elif isinstance(event, EmailsFetched):
            self._total = len(event.emails)
            self.console.print(f"[dim]Fetched [bold]{self._total}[/] recent emails.[/]\n")
        elif isinstance(event, EmailCompleted) and self.show_per_email:
            self._render_email(event)
        elif isinstance(event, RunFinished):
            self._render_summary(event)

    def _render_start(self, ev: RunStarted) -> None:
        self.console.rule(
            f"[bold]courier[/]  ·  mode=[bold]{ev.mode}[/]  ·  workflow={ev.workflow}",
            characters="─",
        )
        self.console.print(f"[dim]run {ev.run_id}[/]\n")

    def _render_email(self, ev: EmailCompleted) -> None:
        brief = ev.brief
        glyph = _STATUS_GLYPH.get(brief.status, "·")
        note = _STATUS_NOTE.get(brief.status, brief.status)
        if brief.draft_id:
            note = f"[green]draft created[/] [dim]{brief.draft_id}[/]"
        if brief.error:
            note = f"[red]{brief.error}[/]"
        subject = brief.subject or "(no subject)"
        if len(subject) > 55:
            subject = subject[:52] + "…"
        contact = brief.contact.email
        if len(contact) > 30:
            contact = contact[:27] + "…"
        self.console.print(
            f"[dim]{ev.index:>2}/{ev.total}[/]  {glyph}  "
            f"[white]{subject:<55}[/]  [dim]{contact:<30}[/]  → {note}"
        )

    def _render_summary(self, ev: RunFinished) -> None:
        run = ev.run
        s = run.summary
        self.console.print()
        self.console.rule(
            f"[bold]Run summary[/]  ·  {_color_status(run.status)}  ·  "
            f"{(run.duration_ms or 0) / 1000:.1f}s",
            characters="─",
        )

        table = Table.grid(padding=(0, 2))
        table.add_column(style="dim", justify="right")
        table.add_column()
        table.add_row("run", f"[bold]{run.id}[/]")
        table.add_row("mode", run.mode.value)
        if s:
            table.add_row("─" * 18, "")
            table.add_row("fetched", str(s.fetched))
            if s.already_drafted:
                table.add_row("already drafted", f"[dim]{s.already_drafted} skipped[/]")
            table.add_row("needs reply", str(s.needs_reply))
            table.add_row("skipped (no reply)", str(s.skipped_no_reply))
            table.add_row("drafts generated", str(s.drafts_generated))
            table.add_row(
                "drafts created",
                f"[bold green]{s.drafts_created}[/]" if s.drafts_created else "0",
            )
            failed_str = f"[bold red]{s.failed}[/]" if s.failed else "0"
            table.add_row("failed", failed_str)
        self.console.print(table)
        self.console.print()

        # Footer hints
        if run.mode.value == "real" and s and s.drafts_created:
            self.console.print(
                "[dim]→ Drafts saved to your Gmail Drafts folder. Open Gmail → Drafts to review.[/]"
            )
        elif run.mode.value == "dry-run" and s and s.drafts_generated:
            self.console.print(
                "[dim]→ Dry-run: drafts shown above were [bold]not[/] created in Gmail.[/]"
            )
        self.console.print(
            f"[dim]→ Inspect this run: [bold]courier --inspect {run.id}[/][/]"
        )


def _color_status(status: str) -> str:
    if status == "completed":
        return f"[green]{status}[/]"
    if status == "completed_with_failures":
        return f"[yellow]{status}[/]"
    if status == "auth_failed":
        return f"[red]{status}[/]"
    return status


def render_inspected_row(row: dict, console: Console | None = None) -> None:
    """Pretty-print a stored run record (from `--inspect RUN_ID`)."""
    console = console or Console()
    console.rule(f"[bold]{row['id']}[/]  ·  {_color_status(row['status'])}", characters="─")
    table = Table.grid(padding=(0, 2))
    table.add_column(style="dim", justify="right")
    table.add_column()
    for key in ("workflow", "mode", "started_at", "finished_at", "duration_ms"):
        val = row.get(key)
        if val is not None:
            table.add_row(key, str(val))
    if row.get("summary_json"):
        import json

        s = json.loads(row["summary_json"])
        table.add_row("─" * 18, "")
        for k, v in s.items():
            table.add_row(k, str(v))
    console.print(table)
