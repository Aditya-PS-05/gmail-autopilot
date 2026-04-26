"""Real Gmail client. Requires google-api-python-client + OAuth credentials.

Install:  pip install -e ".[google]"
Setup:    download an OAuth client_secrets.json from Google Cloud Console
          (Gmail API enabled, Desktop app type), set GOOGLE_CREDENTIALS_PATH.
          On first run a browser window will open; the resulting token is cached
          next to the credentials file as token.json.
"""

from __future__ import annotations

import base64
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path

from ..errors import AuthError, PermanentError, TransientError
from ..models import Contact, CreatedDraft, Email, EmailSummary, Thread

_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
]


class RealGmailClient:
    def __init__(self, credentials_path: Path, token_path: Path | None = None):
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
        except ImportError as e:
            raise PermanentError(
                "google API libraries not installed. Run: uv sync --extra google"
            ) from e

        token_path = token_path or credentials_path.parent / "token.json"
        creds = None
        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path), _SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), _SCOPES)
                creds = flow.run_local_server(port=0)
            token_path.write_text(creds.to_json())
        self._service = build("gmail", "v1", credentials=creds)

    @staticmethod
    def _normalize(exc: Exception) -> Exception:
        try:
            from googleapiclient.errors import HttpError
        except ImportError:
            return TransientError(str(exc))
        if isinstance(exc, HttpError):
            try:
                status = int(exc.resp.status)  # type: ignore[arg-type]
            except (ValueError, TypeError, AttributeError):
                status = 0
            if status in (401, 403):
                return AuthError(str(exc))
            if status == 404:
                return PermanentError(str(exc))
            if status == 429 or status >= 500:
                return TransientError(str(exc))
            return PermanentError(str(exc))
        return TransientError(str(exc))

    def list_recent_emails(self, limit: int) -> list[EmailSummary]:
        try:
            resp = self._service.users().messages().list(userId="me", maxResults=limit).execute()
            return [self._summary_for(m["id"]) for m in resp.get("messages", [])]
        except Exception as e:
            raise self._normalize(e) from e

    def _summary_for(self, message_id: str) -> EmailSummary:
        msg = (
            self._service.users()
            .messages()
            .get(
                userId="me",
                id=message_id,
                format="metadata",
                metadataHeaders=["From", "Subject", "Date"],
            )
            .execute()
        )
        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
        return EmailSummary(
            id=msg["id"],
            thread_id=msg["threadId"],
            sender=_parse_contact(headers.get("From", "")),
            subject=headers.get("Subject", ""),
            snippet=msg.get("snippet", ""),
            received_at=datetime.fromtimestamp(int(msg["internalDate"]) / 1000),
        )

    def read_email(self, message_id: str) -> Email:
        try:
            msg = (
                self._service.users()
                .messages()
                .get(userId="me", id=message_id, format="full")
                .execute()
            )
        except Exception as e:
            raise self._normalize(e) from e
        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
        return Email(
            id=msg["id"],
            thread_id=msg["threadId"],
            sender=_parse_contact(headers.get("From", "")),
            recipients=_parse_contacts(headers.get("To", "")),
            subject=headers.get("Subject", ""),
            body=_extract_body(msg.get("payload", {})),
            received_at=datetime.fromtimestamp(int(msg["internalDate"]) / 1000),
        )

    def read_thread(self, thread_id: str) -> Thread:
        try:
            t = (
                self._service.users()
                .threads()
                .get(userId="me", id=thread_id, format="full")
                .execute()
            )
        except Exception as e:
            raise self._normalize(e) from e
        return Thread(
            id=t["id"],
            messages=[self.read_email(m["id"]) for m in t.get("messages", [])],
        )

    def create_draft(self, thread_id: str, subject: str, body: str) -> CreatedDraft:
        try:
            mime = MIMEText(body)
            mime["Subject"] = subject
            raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()
            draft = (
                self._service.users()
                .drafts()
                .create(
                    userId="me",
                    body={"message": {"raw": raw, "threadId": thread_id}},
                )
                .execute()
            )
            return CreatedDraft(draft_id=draft["id"], thread_id=thread_id)
        except Exception as e:
            raise self._normalize(e) from e


def _parse_contact(s: str) -> Contact:
    s = s.strip()
    if "<" in s and ">" in s:
        name = s.split("<", 1)[0].strip().strip('"').strip()
        email = s.split("<", 1)[1].split(">", 1)[0].strip()
        return Contact(name=name or None, email=email)
    return Contact(email=s)


def _parse_contacts(s: str) -> list[Contact]:
    return [_parse_contact(p) for p in s.split(",") if p.strip()]


def _extract_body(payload: dict) -> str:
    if payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
    for part in payload.get("parts", []):
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
    for part in payload.get("parts", []):
        b = _extract_body(part)
        if b:
            return b
    return ""
