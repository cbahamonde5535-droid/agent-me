"""Web app for the MSW study agent. Run with:  streamlit run app.py"""

import os

import anthropic
from dotenv import load_dotenv
import streamlit as st

from msw_agent.agent import Agent
from msw_agent.tools import extract_text

load_dotenv()

st.set_page_config(page_title="MSW Study Agent", page_icon="📚", layout="wide")

MODES = {
    "Research assistant": "research",
    "Paper feedback": "feedback",
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

    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        st.warning("ANTHROPIC_API_KEY is not set. See the README for setup.")

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
