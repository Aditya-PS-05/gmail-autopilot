"""Interactive draft-review TUI.

After a real-mode run, prompts the user to optionally edit any of the created
drafts. Edits are saved back to Gmail via `drafts.update`. Sending stays in
Gmail's UI — this module never sends mail."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

from .adapters.gmail_base import GmailClient
from .errors import WorkflowError
from .models import EmailActionBrief


def review_drafts(
    briefs: list[EmailActionBrief],
    gmail: GmailClient,
    console: Console,
) -> None:
    """Auto-prompt loop. Lets the user pick a draft, opens its body in $EDITOR,
    and on save calls gmail.update_draft."""
    editable = [b for b in briefs if b.draft_id and b.suggested_message]
    if not editable:
        return

    if (
        not Prompt.ask(
            "\n[bold]Review or edit any drafts?[/] [dim](y/N)[/]",
            choices=["y", "n", "Y", "N", ""],
            default="n",
            show_default=False,
            show_choices=False,
        )
        .lower()
        .startswith("y")
    ):
        return

    while True:
        if not editable:
            console.print("[dim]All drafts reviewed.[/]\n")
            return
        choice = _show_menu(editable, console)
        if choice is None:
            console.print("[dim]Done.[/]\n")
            return
        if _edit_one(editable[choice], gmail, console):
            editable.pop(choice)


def _show_menu(briefs: list[EmailActionBrief], console: Console) -> int | None:
    """Return selected index, or None if user wants to quit."""
    table = Table.grid(padding=(0, 2))
    table.add_column(style="dim", justify="right")
    table.add_column(style="bold")
    table.add_column(style="dim")
    table.add_column()
    for i, b in enumerate(briefs, start=1):
        subject = b.subject if len(b.subject) <= 50 else b.subject[:47] + "…"
        table.add_row(str(i), b.contact.email, "→", subject)
    table.add_row("q", "[dim]quit[/]", "", "")
    console.print()
    console.rule("[bold]Drafts ready in your Gmail Drafts folder[/]", characters="─")
    console.print(table)
    console.print()

    valid_choices = [str(i) for i in range(1, len(briefs) + 1)] + ["q", "Q"]
    raw = Prompt.ask(
        "Pick a draft to edit",
        choices=valid_choices,
        show_choices=False,
        default="q",
    )
    if raw.lower() == "q":
        return None
    return int(raw) - 1


def _edit_one(
    brief: EmailActionBrief,
    gmail: GmailClient,
    console: Console,
) -> bool:
    msg = brief.suggested_message
    if msg is None or not brief.draft_id:
        console.print("[red]No editable draft on this brief.[/]")
        return False

    console.print(
        f"\n[dim]Editing draft to[/] [bold]{brief.contact.email}[/] "
        f"[dim]· subject: {msg.subject}[/]"
    )
    edited = _edit_in_editor(msg.body, suffix=".txt")
    if edited is None:
        console.print("[dim]Editor closed without saving — no changes.[/]")
        return False
    if edited == msg.body:
        console.print("[dim]No changes detected.[/]")
        return False

    try:
        updated = gmail.update_draft(
            draft_id=brief.draft_id,
            subject=msg.subject,
            body=edited,
        )
    except WorkflowError as e:
        console.print(f"[red]✗ Update failed: {e}[/]")
        return False
    except Exception as e:
        console.print(f"[red]✗ Unexpected error: {type(e).__name__}[/]")
        return False

    msg.body = edited  # keep in-memory state in sync for follow-up edits
    console.print(
        f"[green]✓ Updated draft[/] [dim]{updated.draft_id}[/] "
        "[dim]— send from Gmail when you're ready.[/]"
    )
    return True


def _edit_in_editor(initial_text: str, *, suffix: str = ".txt") -> str | None:
    """Open $EDITOR (or VISUAL, or nano fallback) on a temp file pre-filled with
    `initial_text`. Returns the new text on save, or None if editor failed."""
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or _find_default_editor()
    if not editor:
        return None

    fd, path_str = tempfile.mkstemp(suffix=suffix, prefix="courier-")
    path = Path(path_str)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(initial_text)
        proc = subprocess.run([editor, str(path)], check=False)
        if proc.returncode != 0:
            return None
        return path.read_text()
    finally:
        path.unlink(missing_ok=True)


def _find_default_editor() -> str | None:
    for candidate in ("nano", "vim", "vi", "notepad"):
        from shutil import which

        if which(candidate):
            return candidate
    return None
