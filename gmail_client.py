"""
gmail_client.py
Handles Gmail login (OAuth) and fetching/reading emails.
Permissions: read, label, trash, draft and send. It can NOT permanently delete mail.

Run this file once by itself to log in:
    python gmail_client.py
"""

import base64
import json
import os

from bs4 import BeautifulSoup
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# gmail.modify = read + labels + trash (cannot permanently delete)
# gmail.compose = create drafts and send emails
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.compose",
]
CREDENTIALS_FILE = "credentials.json"   # downloaded from Google Cloud Console
TOKEN_FILE = "token.json"               # created automatically after first login

MAX_BODY_CHARS = 3000                   # trim long emails so the AI prompt stays small


def get_service():
    """Log in to Gmail (first time opens a browser) and return the API service."""
    creds = None
    if os.path.exists(TOKEN_FILE):
        # An older login that only had read-only permission can't do actions:
        # remove it so Google asks for the new permissions.
        try:
            with open(TOKEN_FILE) as f:
                saved = set(json.load(f).get("scopes") or [])
        except (ValueError, OSError):
            saved = set()
        if set(SCOPES).issubset(saved):
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        else:
            os.remove(TOKEN_FILE)

    if not creds or not creds.valid:
        refreshed = False
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                refreshed = True
            except RefreshError:
                # Saved login expired or was revoked. While the Google Cloud app is in
                # "Testing" mode, Google expires logins after 7 days. Log in again.
                creds = None
                if os.path.exists(TOKEN_FILE):
                    os.remove(TOKEN_FILE)
        if not refreshed:
            if not os.path.exists(CREDENTIALS_FILE):
                raise FileNotFoundError(
                    "credentials.json not found. Download it from Google Cloud Console "
                    "(see README, step 1)."
                )
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def get_profile_email(service):
    """Return the email address of the connected account."""
    return service.users().getProfile(userId="me").execute(num_retries=3).get("emailAddress", "")


def _decode(data):
    return base64.urlsafe_b64decode(data.encode("utf-8")).decode("utf-8", errors="ignore")


def _extract_body(payload):
    """Walk through the email parts and return plain text (fallback: cleaned HTML)."""
    plain, html = [], []

    def walk(part):
        mime = part.get("mimeType", "")
        data = part.get("body", {}).get("data")
        if data:
            if mime == "text/plain":
                plain.append(_decode(data))
            elif mime == "text/html":
                html.append(_decode(data))
        for sub in part.get("parts", []) or []:
            walk(sub)

    walk(payload)

    if plain:
        text = "\n".join(plain)
    elif html:
        text = BeautifulSoup("\n".join(html), "html.parser").get_text(" ")
    else:
        text = ""

    text = " ".join(text.split())  # collapse extra whitespace
    return text[:MAX_BODY_CHARS]


BATCH_SIZE = 20  # emails fetched per Gmail request (Gmail throttles batches above ~50)


def _parse_message(msg):
    """Turn a raw Gmail API message into a simple dict."""
    headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
    return {
        "id": msg["id"],
        "from": headers.get("from", ""),
        "to": headers.get("to", ""),
        "subject": headers.get("subject", "(no subject)"),
        "date": headers.get("date", ""),
        "snippet": msg.get("snippet", ""),
        "body": _extract_body(msg["payload"]),
        "labels": msg.get("labelIds", []),
        "thread_id": msg.get("threadId"),
        "message_id": headers.get("message-id", ""),
        "reply_to": headers.get("reply-to", ""),
    }


def _get_request(service, msg_id, fmt):
    kw = {"metadataHeaders": ["From", "To", "Subject", "Date"]} if fmt == "metadata" else {}
    return service.users().messages().get(userId="me", id=msg_id, format=fmt, **kw)


def get_email(service, msg_id, fmt="full"):
    """Fetch one email and return a simple dict."""
    msg = _get_request(service, msg_id, fmt).execute(num_retries=3)
    return _parse_message(msg)


def get_emails(service, ids, fmt="full"):
    """Fetch many emails quickly: BATCH_SIZE emails per HTTP request instead of one each."""
    found = {}

    def on_result(request_id, response, exception):
        if exception is None:
            found[request_id] = _parse_message(response)

    for start in range(0, len(ids), BATCH_SIZE):
        batch = service.new_batch_http_request(callback=on_result)
        for msg_id in ids[start:start + BATCH_SIZE]:
            batch.add(_get_request(service, msg_id, fmt), request_id=msg_id)
        try:
            batch.execute()
        except Exception:
            pass  # anything missing is fetched one by one below

    # Any email the batch couldn't get (e.g. Gmail said "slow down") -> fetch individually
    for msg_id in ids:
        if msg_id not in found:
            try:
                found[msg_id] = get_email(service, msg_id, fmt)
            except Exception:
                pass
    return [found[i] for i in ids if i in found]  # keep Gmail's newest-first order


def search_emails(service, query, max_results=10):
    """Search Gmail using normal Gmail search syntax, e.g. 'from:hr newer_than:7d'."""
    resp = service.users().messages().list(
        userId="me", q=query, maxResults=min(max_results, 500)
    ).execute(num_retries=3)
    ids = [m["id"] for m in resp.get("messages", [])]
    return get_emails(service, ids)


def search_email_headers(service, query, max_results=50):
    """Like search_emails but only fetches sender/subject/date (fast, for previews)."""
    resp = service.users().messages().list(
        userId="me", q=query, maxResults=min(max_results, 500)
    ).execute(num_retries=3)
    ids = [m["id"] for m in resp.get("messages", [])]
    return get_emails(service, ids, fmt="metadata")


if __name__ == "__main__":
    svc = get_service()
    print("Logged in as:", get_profile_email(svc))
    for e in search_emails(svc, "in:inbox", max_results=5):
        print(f"- {e['date']} | {e['from']} | {e['subject']}")