# MSW Study Agent

An AI assistant for a Master of Social Work program, built on Claude. It has three modes:

- **Research assistant**: finds peer-reviewed articles (through [OpenAlex](https://openalex.org)) and policy or grey literature (web search). It summarizes sources, builds APA 7 references from verified DOI metadata (through [Crossref](https://www.crossref.org)), and saves sources to a library for each course. You can download a course's library as an alphabetized reference list.
- **Paper feedback coach**: you upload your draft (.docx, .pdf, .txt) and the rubric or assignment instructions. It checks the draft against each rubric item, finds the most important improvements, reviews your argument and evidence, checks the NASW Code of Ethics connections, APA 7 formatting, and bias-free language, and checks your DOIs to see whether your references are real. **It gives feedback and does not rewrite your paper.**

- **Submission check**: upload your paper, and optionally the assignment instructions or rubric.
  - **Free, no API key needed:** automatic APA 7 checks. It flags in-text citations missing from the reference list, references you never cite, years that don't match, "&" vs "and", et al. rules, quotations without page numbers, reference order, DOI format, and "Retrieved from". It also checks your DOIs against Crossref to catch wrong authors or years, and lists phrases often linked to AI-generated writing.
  - **With an API key (usually a few cents):** Claude goes through every bullet point and rubric item, marking each Met, Partly met, or Missing and quoting where it appears in your paper.

> **About AI detection.** This does not give an "AI score", on purpose. AI detectors, including the one in Turnitin, are known to produce false positives, especially for non-native English writers, and no tool can predict what your school's detector will say. The phrase list is only a style hint. The best protection is a writing history: draft in Google Docs or Word with version history turned on.

## Setup (one time)

You need Python 3.10 or newer and an Anthropic API key from <https://console.anthropic.com>. The API charges per use; see "Cost" below.

```bash
git clone https://github.com/cbahamonde5535-droid/agent-me.git && cd agent-me
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # then open .env and paste your API key
```

## Use it

```bash
streamlit run app.py
```

This opens the app in your browser. Pick a mode in the sidebar and type your course (for example `SW 601 Policy`) so saved sources go into the right library.

Example requests for the research assistant:
- "Find 6 peer-reviewed studies since 2018 on trauma-informed care in K-12 schools, and save the best 4 for SW 610."
- "Help me narrow 'homelessness and mental health' into a research question for a policy analysis."
- "Explain ecological systems theory and find a recent article that applies it to foster care."
- "What does the NASW Code of Ethics say about dual relationships? Link the standard."

There is also a terminal version: `python cli.py` (research) or `python cli.py feedback`. In the terminal version, `/file draft.docx` attaches a file.

## Things to know

- **Academic integrity.** Check your syllabus and program AI policy. The agent is built to research and give feedback, not to write your assignments.
- **Client confidentiality.** Never upload real client information from field placement. De-identify everything first. What you send goes to Anthropic's API.
- **Check the citations yourself.** References come from Crossref metadata, which is usually accurate but not always: titles are sometimes in Title Case (the agent flags this, and APA uses sentence case), and page numbers or issue numbers are sometimes missing. Italics show as `*asterisks*`; set them as italics in Word.
- **Paywalls.** The agent reads abstracts and open-access papers only. Get full texts through your university library, and read them before you cite them.
- **Library databases** (PsycINFO, SocINDEX) are not connected. They need your university login.
- **OpenAlex** is free. If searches start failing with an HTTP error, get a free API key at openalex.org and put it in `.env` as `OPENALEX_API_KEY`.

## Cost

The default model is `claude-opus-5` ($5 per million input tokens / $25 per million output tokens). A research question with several searches usually costs a few cents to around $0.30. Feedback on a 10-page paper costs roughly $0.10-$0.50. These are rough estimates, so check the usage page in the Anthropic console. To spend less, set `MSW_AGENT_MODEL=claude-sonnet-5` in `.env` ($2/$10). The quality is a bit lower but still good.

If Claude declines a request, it is automatically retried on a fallback model (the API's `fallbacks: "default"` setting).

## Where your data lives

Saved sources are stored in `data/library.json` on your computer. It is ignored by git, so it won't be uploaded. Conversations are not saved; they end when you close the tab or click "New conversation".

## Development

```bash
pip install pytest && pytest
```

- `msw_agent/agent.py`: the agent loop (tool calls, pause/resume, refusal handling)
- `msw_agent/tools.py`: OpenAlex search, Crossref lookup, APA formatter, course library, file reading
- `msw_agent/checker.py`: rule-based APA 7 checks and AI-phrase scan (no API)
- `msw_agent/prompts.py`: instructions for each mode
- `app.py`: web app; `cli.py`: terminal app
