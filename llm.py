"""
llm.py
One small wrapper so the rest of the app doesn't care which AI model is used.

Choose the main model in .env:
    LLM_PROVIDER=gemini   -> free Gemini API (needs GEMINI_API_KEY)
    LLM_PROVIDER=groq     -> free Groq API (needs GROQ_API_KEY)
    LLM_PROVIDER=ollama   -> local model via Ollama (fully free + private)

Automatic backup:
    If LLM_PROVIDER=gemini and GROQ_API_KEY is also set, any Gemini failure
    (free-tier limit, overload, outage) is automatically retried on Groq.
"""

import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()

PROVIDER = os.getenv("LLM_PROVIDER", "gemini").lower()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")

EMPTY_REPLY = "Sorry, the AI returned an empty answer. Please try asking again."

_gemini_client = None
last_used = None  # which model answered the most recent question (shown in the UI)


def _groq_available():
    return bool(os.getenv("GROQ_API_KEY"))


def _gemini(prompt, system):
    global _gemini_client
    from google import genai
    from google.genai import types

    if _gemini_client is None:
        key = os.getenv("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("GEMINI_API_KEY missing in .env (get one free at aistudio.google.com)")
        # Time limit per request: a stuck Gemini call fails fast (and Groq takes over)
        # instead of making the user wait for minutes. Value is in milliseconds.
        _gemini_client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=30_000))

    # With Groq as backup, give up on Gemini quickly instead of making the user wait.
    attempts = 2 if _groq_available() else 4
    for attempt in range(attempts):
        last = attempt == attempts - 1
        try:
            resp = _gemini_client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(system_instruction=system, temperature=0),
            )
            text = (resp.text or "").strip()
            if not text and not last:
                continue  # Gemini occasionally returns an empty reply -> just ask again
            if not text:
                raise RuntimeError("Gemini returned an empty answer")
            return text
        except Exception as e:
            msg = str(e)
            # 429 = free-tier rate limit, 503 = Google temporarily overloaded -> wait and retry
            if any(s in msg for s in ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE")) and not last:
                time.sleep(3 * (attempt + 1))
                continue
            if "404" in msg or "NOT_FOUND" in msg:
                raise RuntimeError(
                    f"Gemini model '{GEMINI_MODEL}' was not found (Google may have retired it). "
                    "Set GEMINI_MODEL in .env to a current model "
                    "from https://ai.google.dev/gemini-api/docs/models"
                ) from e
            raise


def _groq(prompt, system):
    key = os.getenv("GROQ_API_KEY")
    if not key:
        raise RuntimeError("GROQ_API_KEY missing in .env (get one free at console.groq.com)")

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    for attempt in range(3):
        r = requests.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {key}"},
            json={"model": GROQ_MODEL, "messages": messages, "temperature": 0},
            timeout=60,
        )
        if r.status_code in (429, 503) and attempt < 2:
            # Free-tier per-minute limit hit -> wait as long as Groq asks (max 10s)
            wait = min(float(r.headers.get("retry-after", 3) or 3), 10)
            time.sleep(wait)
            continue
        if r.status_code >= 400:
            raise RuntimeError(f"Groq error {r.status_code}: {r.text[:300]}")
        text = (r.json()["choices"][0]["message"]["content"] or "").strip()
        return text or EMPTY_REPLY
    raise RuntimeError("Groq is busy (rate limit). Please wait a minute and try again.")


def _ollama(prompt, system):
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    r = requests.post(
        f"{OLLAMA_URL}/api/chat",
        json={"model": OLLAMA_MODEL, "messages": messages, "stream": False,
              "options": {"temperature": 0}},
        timeout=300,
    )
    r.raise_for_status()
    return r.json()["message"]["content"].strip()


def ask_llm(prompt, system=None, short_prompt=None):
    """
    Send a prompt to the selected model and return its text reply.

    short_prompt: optional smaller version of the prompt (e.g. shorter email bodies).
    Groq's free tier only allows a few thousand tokens per minute, so Groq gets this one.
    """
    global last_used
    groq_prompt = short_prompt or prompt

    if PROVIDER == "ollama":
        last_used = f"Ollama · {OLLAMA_MODEL}"
        return _ollama(prompt, system)

    if PROVIDER == "groq":
        last_used = f"Groq · {GROQ_MODEL}"
        return _groq(groq_prompt, system)

    # Default: Gemini, with automatic Groq backup if a Groq key is configured
    try:
        reply = _gemini(prompt, system)
        last_used = f"Gemini · {GEMINI_MODEL}"
        return reply
    except Exception as gemini_error:
        if not _groq_available():
            raise
        print(f"[llm] Gemini failed ({str(gemini_error)[:120]}) -> using Groq backup")
        reply = _groq(groq_prompt, system)
        last_used = f"Groq · {GROQ_MODEL} (backup)"
        return reply


def model_name():
    if PROVIDER == "ollama":
        return f"Ollama · {OLLAMA_MODEL}"
    if PROVIDER == "groq":
        return f"Groq · {GROQ_MODEL}"
    backup = f"  ·  backup: Groq · {GROQ_MODEL}" if _groq_available() else ""
    return f"Gemini · {GEMINI_MODEL}{backup}"
