"""Terminal version of the agent.

    python cli.py              # research assistant
    python cli.py feedback     # paper feedback (use /file <path> to attach a draft or rubric)
"""

import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from msw_agent.agent import Agent
from msw_agent.tools import extract_text

load_dotenv()


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "research"
    agent = Agent(mode=mode)
    print(f"MSW agent ({mode} mode, {agent.model}). Commands: /file <path>, /reset, /quit\n")
    attached: list[str] = []
    while True:
        try:
            line = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not line:
            continue
        if line == "/quit":
            return
        if line == "/reset":
            agent.reset()
            attached.clear()
            print("(conversation cleared)")
            continue
        if line.startswith("/file "):
            path = Path(line[6:].strip()).expanduser()
            try:
                text = extract_text(path.name, path.read_bytes())
            except (OSError, ValueError) as e:
                print(f"(could not read file: {e})")
                continue
            attached.append(f'<document filename="{path.name}">\n{text}\n</document>')
            print(f"(attached {path.name}, {len(text.split())} words; it will be sent with your next message)")
            continue

        content = "\n\n".join(attached + [line])
        attached.clear()
        try:
            reply = agent.send(content, on_event=lambda kind, d: print(f"  [{kind}] {d}"))
        except anthropic.APIError as e:
            print(f"(API error: {e})")
            continue
        print(f"\nagent> {reply.text}\n")


if __name__ == "__main__":
    main()
