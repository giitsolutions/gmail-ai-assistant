"""
actions.py
Everything that CHANGES Gmail: labels, trash, drafts, sending.

Safety rules built in:
  * "delete" always means Move to Trash (Gmail keeps it 30 days, so it can be undone).
    Permanent delete is intentionally NOT supported.
  * Every action works on a list of email ids that the user has already seen and confirmed.
  * At most MAX_ACTION_EMAILS emails per action.
"""

import base64
from email.message import EmailMessage
from email.utils import parseaddr

MAX_ACTION_EMAILS = 50

# action -> (labels to add, labels to remove)
LABEL_CHANGES = {
    "mark_read":      ([], ["UNREAD"]),
    "mark_unread":    (["UNREAD"], []),
    "star":           (["STARRED"], []),
    "unstar":         ([], ["STARRED"]),
    "archive":        ([], ["INBOX"]),
    "move_to_inbox":  (["INBOX"], []),
    "important":      (["IMPORTANT"], []),
    "not_important":  ([], ["IMPORTANT"]),
    "spam":           (["SPAM"], ["INBOX"]),
    "not_spam":       (["INBOX"], ["SPAM"]),
}
TRASH_ACTIONS = {"trash", "restore_from_trash"}
LABEL_ACTIONS = {"add_label", "remove_label"}

ACTION_TEXT = {
    "mark_read": "Mark as read",
    "mark_unread": "Mark as unread",
    "star": "Add a star to",
    "unstar": "Remove the star from",
    "archive": "Archive (remove from Inbox)",
    "move_to_inbox": "Move to Inbox",
    "important": "Mark as important",
    "not_important": "Mark as not important",
    "spam": "Report as spam / move to Spam",
    "not_spam": "Not spam: move back to Inbox",
    "trash": "Move to Trash",
    "restore_from_trash": "Restore from Trash",
    "add_label": "Add label",
    "remove_label": "Remove label",
}
INVERSE = {
    "mark_read": "mark_unread", "mark_unread": "mark_read",
    "star": "unstar", "unstar": "star",
    "archive": "move_to_inbox", "move_to_inbox": "archive",
    "important": "not_important", "not_important": "important",
    "spam": "not_spam", "not_spam": "spam",
    "trash": "restore_from_trash", "restore_from_trash": "trash",
    "add_label": "remove_label", "remove_label": "add_label",
}
ALL_ACTIONS = set(ACTION_TEXT)


def describe(action, label=None):
    text = ACTION_TEXT[action]
    return f"{text} “{label}”" if action in LABEL_ACTIONS and label else text


def _label_id(service, name, create=False):
    labels = service.users().labels().list(userId="me").execute(num_retries=3).get("labels", [])
    for lb in labels:
        if lb["name"].lower() == name.lower():
            return lb["id"]
    if not create:
        return None
    body = {"name": name, "labelListVisibility": "labelShow", "messageListVisibility": "show"}
    return service.users().labels().create(userId="me", body=body).execute(num_retries=3)["id"]


def run_action(service, action, ids, label=None):
    """Apply one action to the given email ids. Returns how many emails were changed."""
    if action not in ALL_ACTIONS:
        raise ValueError(f"Unknown action: {action}")
    ids = list(dict.fromkeys(ids))[:MAX_ACTION_EMAILS]
    if not ids:
        return 0
    msgs = service.users().messages()

    if action in TRASH_ACTIONS:
        for i in ids:
            (msgs.trash if action == "trash" else msgs.untrash)(userId="me", id=i).execute(num_retries=3)
        return len(ids)

    if action in LABEL_ACTIONS:
        if not label:
            raise ValueError("A label name is needed.")
        lid = _label_id(service, label, create=(action == "add_label"))
        if lid is None:
            raise ValueError(f"Label “{label}” does not exist.")
        add, remove = ([lid], []) if action == "add_label" else ([], [lid])
    else:
        add, remove = LABEL_CHANGES[action]

    msgs.batchModify(userId="me", body={"ids": ids, "addLabelIds": add, "removeLabelIds": remove}
                     ).execute(num_retries=3)
    return len(ids)


# ---------- Writing emails ----------

def _raw_message(to, subject, body, in_reply_to=None):
    address = parseaddr(to)[1]
    if "@" not in address:
        raise ValueError("Please enter a valid email address in the 'To' box.")
    m = EmailMessage()
    m["To"] = address
    m["Subject"] = subject or "(no subject)"
    if in_reply_to:
        m["In-Reply-To"] = in_reply_to
        m["References"] = in_reply_to
    m.set_content(body)
    return base64.urlsafe_b64encode(m.as_bytes()).decode()


def save_draft(service, to, subject, body, thread_id=None, in_reply_to=None):
    """Save the message in Gmail > Drafts (nothing is sent)."""
    message = {"raw": _raw_message(to, subject, body, in_reply_to)}
    if thread_id:
        message["threadId"] = thread_id
    return service.users().drafts().create(userId="me", body={"message": message}).execute(num_retries=3)["id"]


def send_message(service, to, subject, body, thread_id=None, in_reply_to=None):
    """Send the message right now."""
    message = {"raw": _raw_message(to, subject, body, in_reply_to)}
    if thread_id:
        message["threadId"] = thread_id
    # no retries here: a retry could send the email twice
    return service.users().messages().send(userId="me", body=message).execute()["id"]