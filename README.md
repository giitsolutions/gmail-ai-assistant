# Gmail AI Assistant

Ask questions in plain English about a Gmail inbox, for example *"How many rejections did I get last month?"*, *"Summarize my emails from this week"* or *"Any unread emails from HR?"*. The app answers from the actual emails and shows which emails it used.

**100% free stack:** Python · Gmail API · Gemini 3.5 Flash-Lite (main) · Groq gpt-oss-120b (automatic backup) · optional Ollama (local) · Streamlit

---

## How it works

```
User question  ("how many rejections did I get last month?")
   │
   ▼
① AI turns the question into a Gmail search
      → (rejection OR unfortunately OR "not selected") newer_than:30d
   │
   ▼
② Gmail API fetches the matching emails (read-only, 20 per request)
   │
   ▼
③ AI reads those emails and answers, citing each email it used as [Email N]
   │
   ▼
④ App shows the answer + only the cited emails as "Sources"
```

This "search first, then answer" design (a simple form of RAG, Retrieval-Augmented Generation) means the AI only sees the emails it needs. It doesn't invent facts, and every answer can be checked against its sources.

### AI models and automatic backup

| Role | Model | Why |
|---|---|---|
| Main | **Gemini 3.5 Flash-Lite** (Google, free tier) | Fast (about 3 s), large context, most generous free limits |
| Backup | **Groq · openai/gpt-oss-120b** (free tier) | Used automatically if Gemini hits its limit, is overloaded or takes more than 30 s |
| Optional | **Ollama** (local model) | Fully private: emails never leave the laptop |

Each answer shows which model answered it ("Answered by Gemini…" or "Answered by Groq… (backup)").

---

## Project structure

| File | What it does |
|---|---|
| `app.py` | Streamlit chat screen: sidebar, chat, sources, warnings |
| `assistant.py` | The logic: question → Gmail search → answer, citations, counting rules |
| `gmail_client.py` | Gmail login (OAuth, read-only) and fast batch fetching of emails |
| `llm.py` | Calls the AI model: Gemini → Groq backup, or Ollama; retries and time limits |
| `requirements.txt` | Python packages |
| `.env.example` | Settings template (copy to `.env`) |

Files created during setup (never share or upload these, they are in `.gitignore`):
`credentials.json` (Google OAuth client), `token.json` (your Gmail login), `.env` (API keys).

---

## Setup (about 20 minutes, one time)

### Step 1: Gmail API credentials

1. Go to https://console.cloud.google.com and create a **new project** (e.g. `Gmail-AI-Assistant`). Make sure it is selected in the top bar.
2. Search for **Gmail API** and click **Enable**.
3. Open **Google Auth Platform** (older consoles: *OAuth consent screen*) → **Get started**:
   - App name: `Gmail AI Assistant`, support email: yours
   - Audience: **External**
   - Then go to **Audience → Test users → Add users** and add the Gmail address you want to connect. **This step is required**, otherwise login shows "Access blocked".
4. Go to **Clients → Create client** → Application type **Desktop app** → **Create** → **Download JSON**.
5. Rename the file to **`credentials.json`** and put it in this folder.
   > On Windows, file extensions are often hidden, so the file can end up named `credentials.json.json`. Check this if login says the file is not found.

### Step 2: Free API keys

1. **Gemini (required):** https://aistudio.google.com/apikey → *Create API key*.
2. **Groq (optional, recommended backup):** https://console.groq.com/keys → *Create API Key* (starts with `gsk_`).
3. Copy `.env.example` to `.env` and paste the keys:
   ```
   GEMINI_API_KEY=your_gemini_key
   GROQ_API_KEY=your_groq_key      # leave empty to turn off the backup
   ```

### Step 3: Install

```bash
pip install -r requirements.txt
```

### Step 4: Log in to Gmail (first time only)

```bash
python gmail_client.py
```
A browser opens. Choose the test3-user account. On *"Google hasn't verified this app"*, click **Continue**, then allow read access. The terminal should print your 5 latest emails. This creates `token.json`, so you won't need to log in again.

---

## Run

```bash
cd path\to\gmail-ai-assistant
python -m streamlit run app.py
```
The app opens at **http://localhost:8501**. Stop it with **Ctrl + C**.
First run only: if Streamlit asks for an email in the terminal, just press Enter.

---

## Using the app

- **Emails to read per question** (sidebar slider, 3–100):
  - **10**: normal questions (about 3–5 s)
  - **30–50**: weekly or monthly summaries
  - **100**: big overviews (about 15–25 s); each email is shortened so the request stays fast
- **Sources:** under each answer, *"📎 Sources"* lists **only the emails the answer used**.
- **Search line:** shows the exact Gmail search the AI made and how many emails were read.
- **Limit warning:** if the search found as many emails as the slider limit, the app warns you that some may not have been read. Raise the slider for complete counts.

### Accuracy and consistent counts

Counting questions ("how many rejections…") are handled with extra care:
- Temperature is set to **0**, so the model gives the same answer to the same input.
- The same question asked on the same day reuses the **same Gmail search**, so it reads the same emails.
- The AI must list every matching email first and give **"Total: N" at the end**, where N equals the list.
- Unclear emails (e.g. "we received your application") are listed separately as **not counted**.

The count is still the AI's *judgement* of each email, not a database count. Check the Sources list for anything important.

---

## Settings (`.env`)

| Setting | Default | Meaning |
|---|---|---|
| `LLM_PROVIDER` | `gemini` | Main model: `gemini`, `groq` or `ollama` |
| `GEMINI_API_KEY` | — | Gemini key (required for `gemini`) |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | Gemini model name |
| `GROQ_API_KEY` | empty | Groq key; if set, Groq is the automatic backup |
| `GROQ_MODEL` | `openai/gpt-oss-120b` | Groq model name |
| `OLLAMA_MODEL` | `llama3.1:8b` | Local model (only for `ollama`) |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama address |

Restart the app after changing `.env`.

### Optional: fully private mode with Ollama
1. Install Ollama from https://ollama.com
2. `ollama pull llama3.1:8b`
3. In `.env` set `LLM_PROVIDER=ollama`

Emails then never leave the laptop. This needs about 8–16 GB RAM, and answers are slower.

---

## Free-tier limits (checked November 2026)

| Service | Free limit (approx.) | Per question |
|---|---|---|
| Gmail API | Very high, effectively unlimited for one user | 1 search + batch fetch |
| Gemini 3.5 Flash-Lite | ~500 requests/day, ~10/minute | 2 requests |
| Groq gpt-oss-120b | 1,000 requests/day, 8,000 tokens/minute | 2 requests, ~4k tokens |

Google and Groq change models and limits often. If a model is retired, the app shows a clear "model not found" error. Pick a current model from https://ai.google.dev/gemini-api/docs/models or https://console.groq.com/docs/models and update `.env`.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `credentials.json not found` | Check the file name (hidden `.json.json` extension) and that it's in this folder |
| "Access blocked" / `Error 403: access_denied` at login | Add the Gmail address under **Audience → Test users** |
| `WinError 10053 … connection was aborted` | Fixed in code: fresh Gmail connection per question plus retries. Restart the app if seen |
| `Gemini model '…' was not found` | Model retired by Google: change `GEMINI_MODEL` in `.env` |
| `503 UNAVAILABLE` / high demand | Temporary Google overload: the app retries, then switches to Groq |
| Slow answers | Lower the slider; avoid many questions per minute (free-tier limits) |
| Login expired / wrong account | Delete `token.json` and run `python gmail_client.py` again |

---

## Security and privacy

- **Read-only:** the app uses the `gmail.readonly` scope, so it can never send, delete or change an email.
- **Data sent to AI providers:** the emails relevant to each question are sent to Gemini (or Groq). On free tiers, providers may use requests to improve their products. **For a company inbox**, use keys created from a company account, or use Ollama mode.
- **Never share or upload** `credentials.json`, `token.json` or `.env`.

## Ideas to extend

- Daily email digest sent automatically
- Vector database (ChromaDB) over the whole inbox for semantic search
- Reading attachments (PDF text extraction)
- Drafting replies (needs the `gmail.compose` scope)
- Multi-user web login (web OAuth flow) and deployment
- Exact counting with structured extraction (AI labels each email as JSON, Python counts)
