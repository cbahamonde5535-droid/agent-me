"""Web app for the MSW study agent. Run with:  streamlit run app.py"""

import os

import anthropic
from dotenv import load_dotenv
import streamlit as st

from msw_agent.agent import Agent
from msw_agent.checker import check_paper, report_markdown, verify_dois
from msw_agent.tools import extract_text, fetch_crossref

load_dotenv()

st.set_page_config(page_title="MSW Study Agent", page_icon="📚", layout="wide")

MODES = {
    "Research assistant": "research",
    "Paper feedback": "feedback",
    "Submission check": "checklist",
}


def get_agent(mode: str) -> Agent:
    key = f"agent_{mode}"
    if key not in st.session_state:
        st.session_state[key] = Agent(mode=mode)
        st.session_state[f"chat_{mode}"] = []
    return st.session_state[key]


def run_turn(agent: Agent, mode: str, content, shown_text: str) -> None:
    chat = st.session_state[f"chat_{mode}"]
    chat.append({"role": "user", "text": shown_text})
    with st.chat_message("user"):
        st.markdown(shown_text)
    with st.chat_message("assistant"):
        status = st.status("Working…", expanded=False)

        def on_event(kind: str, detail: str) -> None:
            status.write(("🔎 " if kind == "tool" else "⚠️ ") + detail)

        try:
            reply = agent.send(content, on_event=on_event)
        except anthropic.AuthenticationError:
            status.update(label="Error", state="error")
            st.error("Your Anthropic API key was rejected. Check ANTHROPIC_API_KEY.")
            return
        except anthropic.RateLimitError:
            status.update(label="Error", state="error")
            st.error("Rate limited by the API. Wait a minute and try again.")
            return
        except anthropic.APIConnectionError:
            status.update(label="Error", state="error")
            st.error("Could not reach the Anthropic API. Check your internet connection.")
            return
        except anthropic.APIStatusError as e:
            status.update(label="Error", state="error")
            st.error(f"API error ({e.status_code}): {e.message}")
            return
        status.update(label="Done", state="complete")
        text = reply.text or "_(no answer)_"
        for n in reply.notices:
            text += f"\n\n> ⚠️ {n}"
        st.markdown(text)
    chat.append({"role": "assistant", "text": text})


# --- Sidebar ---------------------------------------------------------------
with st.sidebar:
    st.title("📚 MSW Study Agent")
    mode_label = st.radio("Mode", list(MODES))
    mode = MODES[mode_label]
    course = st.text_input("Course", value=st.session_state.get("course", ""), placeholder="e.g. SW 601 Policy")
    st.session_state["course"] = course

    has_key = bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
    if not has_key:
        st.warning(
            "ANTHROPIC_API_KEY is not set, so only the free checks in Submission check will work. "
            "See the README for setup."
        )

    if st.button("New conversation"):
        st.session_state.pop(f"agent_{mode}", None)
        st.session_state.pop(f"chat_{mode}", None)
        st.rerun()

    agent = get_agent(mode)

    st.divider()
    st.subheader("Saved sources")
    courses = agent.library.courses()
    if courses:
        pick = st.selectbox("Course library", courses, index=courses.index(course) if course in courses else 0)
        entries = agent.library.entries(pick)
        for e in entries:
            with st.expander(e["title"][:70]):
                st.markdown(e["apa"])
                st.caption(e.get("summary", ""))
                if e.get("warnings"):
                    st.caption("⚠️ " + " ".join(e["warnings"]))
                if st.button("Remove", key=f"rm_{pick}_{e['doi']}"):
                    agent.library.remove(pick, e["doi"])
                    st.rerun()
        st.download_button(
            "Download APA reference list",
            agent.library.reference_list(pick),
            file_name=f"references-{pick}.txt".replace(" ", "_"),
        )
        st.caption("Italics are marked with *asterisks*; apply italics when you paste into Word.")
    else:
        st.caption("No sources yet. Ask the research assistant to save some.")

    u = agent.usage
    st.divider()
    st.caption(
        f"Model: {agent.model} · tokens this session: "
        f"{u['input_tokens'] + u['cache_read_input_tokens']:,} in / {u['output_tokens']:,} out"
    )

# --- Main area -------------------------------------------------------------
st.header(mode_label)
course_note = f"(Course: {course})\n\n" if course else ""

if mode == "research":
    st.caption(
        "Ask for sources on a topic, help narrowing a research question, or explanations of theories. "
        "Say “save these” to add sources to your course library."
    )
elif mode == "checklist":
    st.caption(
        "Upload your paper to check APA 7 citations and references (free, no API key needed). "
        "Add the assignment instructions or rubric to have Claude check every bullet point."
    )
    col1, col2 = st.columns(2)
    paper_file = col1.file_uploader("Your paper", type=["docx", "pdf", "txt", "md"], key="chk_paper")
    instr_files = col2.file_uploader(
        "Instructions / rubric (optional, can be several files)",
        type=["docx", "pdf", "txt", "md"], accept_multiple_files=True, key="chk_instr",
    )
    verify = st.checkbox("Also verify DOIs against Crossref (free, needs internet)", value=True)
    b1, b2 = st.columns(2)
    run_free = b1.button("Run free APA checks", disabled=paper_file is None, type="primary")
    run_claude = b2.button(
        "Check every requirement with Claude",
        disabled=paper_file is None or not instr_files or not has_key,
        help="Needs an API key and the instructions. Usually costs a few cents.",
    )

    paper = ""
    if paper_file is not None and (run_free or run_claude):
        try:
            paper = extract_text(paper_file.name, paper_file.getvalue())
        except Exception as e:
            st.error(f"Could not read the file: {e}")
            st.stop()
        if not paper:
            st.error("No text found in the paper. If it's a scanned PDF, upload the .docx instead.")
            st.stop()
        report = check_paper(paper)
        extra = []
        if verify and report.references:
            with st.spinner("Checking DOIs with Crossref…"):
                extra = verify_dois(report.references, fetch_crossref)
        st.session_state["chk_report"] = (paper_file.name, report, report_markdown(report, extra))

    if "chk_report" in st.session_state:
        name, report, md = st.session_state["chk_report"]
        with st.expander(f"Automatic APA check: {name}", expanded=True):
            st.markdown(md)
            st.caption(
                "Automatic checks read plain text: they can't see italics, hanging indents, or "
                "double spacing, and unusual citations (secondary sources, laws, personal "
                "communications) may be reported by mistake. Treat each item as “check this”."
            )
            st.download_button("Download this report", md, file_name=f"apa-check-{name}.md")

    if run_claude:
        instructions = []
        for f in instr_files:
            try:
                instructions.append(f'<instructions filename="{f.name}">\n{extract_text(f.name, f.getvalue())}\n</instructions>')
            except Exception as e:
                st.error(f"Could not read {f.name}: {e}")
                st.stop()
        _, report, _ = st.session_state["chk_report"]
        stats = (
            f"Automatic checks: the paper has {report.word_count:,} words before the reference list, "
            f"{len(report.citations)} in-text citations, and {len(report.references)} references."
        )
        content = "\n\n".join(
            [course_note + "Check my paper against every requirement in the instructions.", stats]
            + instructions
            + [f'<paper filename="{paper_file.name}">\n{paper}\n</paper>']
        )
        for msg in st.session_state[f"chat_{mode}"]:
            with st.chat_message(msg["role"]):
                st.markdown(msg["text"])
        shown = f"Check **{paper_file.name}** against " + ", ".join(f"**{f.name}**" for f in instr_files) + "."
        run_turn(agent, mode, content, shown)
        st.stop()
else:
    st.caption(
        "Upload your draft and the rubric or assignment instructions. You'll get feedback, not a rewrite. "
        "Remove any real client details before uploading."
    )
    col1, col2 = st.columns(2)
    draft_file = col1.file_uploader("Your draft", type=["docx", "pdf", "txt", "md"])
    rubric_file = col2.file_uploader("Rubric / instructions (optional)", type=["docx", "pdf", "txt", "md"])
    focus = st.text_input("Anything specific to focus on? (optional)", placeholder="e.g. my literature review section, APA")
    if st.button("Get feedback", disabled=draft_file is None, type="primary"):
        try:
            draft = extract_text(draft_file.name, draft_file.getvalue())
            rubric = extract_text(rubric_file.name, rubric_file.getvalue()) if rubric_file else ""
        except Exception as e:  # unreadable or scanned file
            st.error(f"Could not read the file: {e}")
            st.stop()
        if not draft:
            st.error("No text found in the draft. If it's a scanned PDF, upload the .docx instead.")
            st.stop()
        parts = [course_note + "Please review my draft."]
        if focus:
            parts.append(f"Focus especially on: {focus}")
        if rubric:
            parts.append(f"<rubric filename=\"{rubric_file.name}\">\n{rubric}\n</rubric>")
        else:
            parts.append("(No rubric provided.)")
        parts.append(f"<draft filename=\"{draft_file.name}\">\n{draft}\n</draft>")
        shown = f"Please review my draft **{draft_file.name}**" + (f" against **{rubric_file.name}**" if rubric_file else "") + "."
        for msg in st.session_state[f"chat_{mode}"]:
            with st.chat_message(msg["role"]):
                st.markdown(msg["text"])
        run_turn(agent, mode, "\n\n".join(parts), shown)
        st.stop()

for msg in st.session_state[f"chat_{mode}"]:
    with st.chat_message(msg["role"]):
        st.markdown(msg["text"])

prompt = st.chat_input("Ask a question…")
if prompt:
    run_turn(agent, mode, course_note + prompt, prompt)
