"""
app.py — Streamlit chat interface.
Run with:  python -m streamlit run app.py
"""

import uuid

import streamlit as st

import llm
from actions import INVERSE, describe, run_action, save_draft, send_message
from assistant import handle_request
from gmail_client import get_profile_email, get_service
from llm import model_name

st.set_page_config(page_title="Gmail AI Assistant", page_icon="📬")

if "messages" not in st.session_state:
    st.session_state.messages = []


def add_message(role, content):
    st.session_state.messages.append({"role": role, "content": content})


@st.cache_resource
def connect_gmail():
    service = get_service()
    return service, get_profile_email(service)


# ---------- Sidebar ----------
with st.sidebar:
    st.title("📬 Gmail AI Assistant")
    try:
        service, email = connect_gmail()
        st.success(f"Connected: {email}")
    except Exception as e:
        st.error(f"Gmail not connected:\n\n{e}")
        st.stop()

    st.caption(f"Model: {model_name()}")
    max_emails = st.slider(
        "Emails to read per question", 3, 100, 10,
        help="10 is best for most questions. Use more for big summaries "
             "(e.g. 'everything from last month'). More emails = slower answers.",
    )
    show_sources = st.toggle("Show emails used", value=True)
    if st.button("Clear chat"):
        st.session_state.messages = []
        st.session_state.pending = None
        st.rerun()

    undo = st.session_state.get("undo")
    if undo:
        st.divider()
        if st.button(f"↩ Undo: {undo['text']}"):
            try:
                run_action(get_service(), undo["action"], undo["ids"], undo.get("label"))
                add_message("assistant", f"↩ Undone: {undo['text']}.")
                st.session_state.undo = None
                st.rerun()
            except Exception as e:
                st.error(f"Undo failed: {e}")

    st.markdown("**Try asking:**")
    st.markdown(
        "- Summarize my emails from this week\n"
        "- Any unread emails from HR?\n"
        "- Mark all emails from Quick Heal as read\n"
        "- Move Flipkart promotions to trash\n"
        "- Star emails from my professor\n"
        "- Reply to Anjali saying I'm interested\n"
        "- Write an email to abc@gmail.com asking for a leave"
    )
    st.caption("Changes always ask for your confirmation first. Deleting = Trash (recoverable for 30 days).")

question = st.chat_input("Ask about your emails, or tell me what to do with them...")
if question:
    st.session_state.pending = None  # a new request replaces any unconfirmed one


# ---------- Chat history ----------
for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])


# ---------- Confirmation box for changes / drafts ----------
def finish(text, undo=None):
    add_message("assistant", text)
    st.session_state.pending = None
    if undo is not None:
        st.session_state.undo = undo
    st.rerun()


def render_pending():
    p = st.session_state.get("pending")
    if not p:
        return
    pid = p["id"]
    with st.chat_message("assistant"):
        if p["type"] == "action":
            what = describe(p["action"], p["label"])
            st.markdown(f"**Please confirm:** {what} · **{len(p['emails'])} email(s)**")
            if p["limited"]:
                st.caption("Gmail found more matches. Only the first 50 are included; ask again for the rest.")
            with st.expander("Emails that will be changed", expanded=True):
                for e in p["emails"]:
                    st.markdown(f"- **{e['subject']}**  \n  {e['from']} · {e['date']}")
            c1, c2 = st.columns(2)
            if c1.button("✅ Confirm", key=f"ok_{pid}", type="primary"):
                try:
                    ids = [e["id"] for e in p["emails"]]
                    n = run_action(get_service(), p["action"], ids, p["label"])
                except Exception as e:
                    st.error(f"Could not do it: {e}")
                else:
                    finish(f"✅ Done: {what} ({n} email(s)).",
                           undo={"action": INVERSE[p["action"]], "ids": ids, "label": p["label"],
                                 "text": f"{describe(INVERSE[p['action']], p['label'])} ({n})"})
            if c2.button("Cancel", key=f"no_{pid}"):
                finish("Cancelled. Nothing was changed.")

        elif p["type"] == "message":
            st.markdown("**Draft: review and edit, then choose what to do**")
            to = st.text_input("To", p["to"], key=f"to_{pid}")
            subject = st.text_input("Subject", p["subject"], key=f"subj_{pid}")
            body = st.text_area("Message", p["body"], height=220, key=f"body_{pid}")
            c1, c2, c3 = st.columns(3)
            args = (to, subject, body, p.get("thread_id"), p.get("in_reply_to"))
            if c1.button("💾 Save as draft", key=f"sd_{pid}"):
                try:
                    save_draft(get_service(), *args)
                except Exception as e:
                    st.error(f"Could not save the draft: {e}")
                else:
                    finish(f"💾 Saved to your Gmail Drafts (to {to}). Nothing was sent.")
            if c2.button("📨 Send now", key=f"send_{pid}", type="primary"):
                try:
                    send_message(get_service(), *args)
                except Exception as e:
                    st.error(f"Could not send: {e}")
                else:
                    finish(f"📨 Email sent to {to}.")
            if c3.button("Discard", key=f"dis_{pid}"):
                finish("Draft discarded. Nothing was sent.")


render_pending()


# ---------- New question ----------
if question:
    add_message("user", question)
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        with st.spinner("Working on it..."):
            try:
                history = st.session_state.messages[:-1]
                # Fresh Gmail connection per request: a cached one can be dropped by
                # Windows while idle (WinError 10053) and isn't safe across Streamlit threads.
                result = handle_request(get_service(), question, history, max_emails)
            except Exception as e:
                result = {"type": "error", "text": f"⚠️ Error: {e}"}
                llm.last_used = None

    kind = result["type"]
    if kind == "answer":
        reply, query, cited, total_read = (result["reply"], result["query"],
                                           result["cited"], result["total_read"])
        with st.chat_message("assistant"):
            st.markdown(reply)
            if llm.last_used:
                st.caption(f"Answered by {llm.last_used}")

            # Show only the emails the answer actually used, not everything that was read
            if show_sources and cited:
                with st.expander(f"📎 Sources: {len(cited)} email(s) used for this answer"):
                    for n, e in cited:
                        st.markdown(f"**[Email {n}] {e['subject']}**  \n{e['from']} · {e['date']}  \n"
                                    f"_{e['snippet']}_")
                        st.divider()
            if show_sources and query:
                st.caption(f"🔎 Searched Gmail for `{query}` · read {total_read} emails")
            if query and total_read >= max_emails:
                st.warning(f"Read {total_read} emails, the slider limit. There may be more matching "
                           "emails that were not read. Raise 'Emails to read per question' in the "
                           "sidebar, or ask a narrower question.")
        add_message("assistant", reply)
    else:
        if kind == "action":
            st.session_state.pending = {**result, "id": uuid.uuid4().hex}
            text = f"I found **{len(result['emails'])}** email(s). Please confirm below to proceed."
        elif kind == "message":
            st.session_state.pending = {**result, "id": uuid.uuid4().hex}
            text = "I wrote a draft. Review it below."
        else:  # clarify / error
            text = result["text"]
        add_message("assistant", text)
        st.rerun()