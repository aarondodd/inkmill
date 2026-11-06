"""A stand-in for the claude program, for the AI Assistant's Claude Code tests.

It logs each call (arguments, working folder, prompt) to FAKE_CLAUDE_LOG and
answers in Claude Code's stream-json shape. The prompt picks the behavior:
"LOGIN" fails as if not logged in, "READ" first uses the Read tool, and a
resume of the id "gone" reports a missing conversation.
"""

import json
import os
import sys
import uuid


def emit(data):
    print(json.dumps(data), flush=True)


def delta(text):
    emit({"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": text}}})


def main():
    args = sys.argv[1:]
    prompt = sys.stdin.read()
    with open(os.environ["FAKE_CLAUDE_LOG"], "a", encoding="utf-8") as log:
        log.write(json.dumps({"args": args, "cwd": os.getcwd(), "prompt": prompt}) + "\n")
    session = str(uuid.uuid4())
    for flag in ("--session-id", "--resume"):
        if flag in args:
            session = args[args.index(flag) + 1]
    if "--resume" in args and session == "gone":
        emit({"type": "result", "subtype": "error_during_execution", "is_error": True, "session_id": session,
              "errors": [f"No conversation found with session ID: {session}"]})
        return
    emit({"type": "system", "subtype": "init", "session_id": session})
    if "LOGIN" in prompt:
        emit({"type": "result", "is_error": True, "result": "Not logged in \u00b7 Please run /login", "session_id": session})
        sys.exit(1)
    emit({"type": "stream_event", "event": {"type": "message_start"}})
    if "READ" in prompt:
        delta("I'll read the chapter. ")
        emit({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Read", "input": {"file_path": "/x/chapter-01.md"}}]}})
        emit({"type": "stream_event", "event": {"type": "message_start"}})
    pieces = ["One\n---\n", "Two\n---\nThree"]
    for piece in pieces:
        delta(piece)
    emit({"type": "result", "subtype": "success", "is_error": False, "result": "".join(pieces), "session_id": session})


main()
