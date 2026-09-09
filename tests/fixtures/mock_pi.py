"""Deterministic mock of `pi --mode rpc` for adapter contract tests.

Protocol behavior is configured via environment variables:

- ``MOCK_PI_TEXT``: reply text for the first prompt (default: valid
  minimal DiscoveryResult JSON);
- ``MOCK_PI_REPAIR_TEXT``: reply for subsequent prompts (repair path);
- ``MOCK_PI_WRITE_PROBE=1``: the capability probe prompt causes the mock
  to actually create probe.txt (simulating a write-capable agent);
- ``MOCK_PI_DIE_ON_PROMPT=1``: stream closes after accepting a prompt
  (simulating a crashed agent).
"""

import json
import os
import sys


def send(obj) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main() -> None:
    reply = os.environ.get(
        "MOCK_PI_TEXT",
        '{"task_kind":"CHANGE","current_state":"mock current state","relevant_components":["src/"]}',
    )
    repair_reply = os.environ.get("MOCK_PI_REPAIR_TEXT", reply)
    write_probe = os.environ.get("MOCK_PI_WRITE_PROBE") == "1"
    die = os.environ.get("MOCK_PI_DIE_ON_PROMPT") == "1"
    prompts_seen = 0
    current_text = reply

    for line in sys.stdin:
        try:
            cmd = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        ctype = cmd.get("type")
        if ctype == "get_state":
            send(
                {
                    "id": cmd.get("id"),
                    "type": "response",
                    "command": "get_state",
                    "success": True,
                    "data": {"model": {"id": "mock"}},
                }
            )
        elif ctype == "prompt":
            send(
                {
                    "id": cmd.get("id"),
                    "type": "response",
                    "command": "prompt",
                    "success": True,
                }
            )
            if die:
                return
            prompts_seen += 1
            current_text = reply if prompts_seen == 1 else repair_reply
            message = cmd.get("message", "")
            if write_probe and "probe.txt" in message:
                with open("probe.txt", "w", encoding="utf-8") as fh:
                    fh.write("x")
                send({"type": "agent_start"})
                send({"type": "agent_settled"})
                continue
            send({"type": "agent_start"})
            send(
                {
                    "type": "message_end",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": current_text}],
                    },
                }
            )
            send({"type": "agent_settled"})
        elif ctype == "get_last_assistant_text":
            send(
                {
                    "id": cmd.get("id"),
                    "type": "response",
                    "command": "get_last_assistant_text",
                    "success": True,
                    "data": {"text": current_text},
                }
            )
        elif ctype == "abort":
            send(
                {
                    "id": cmd.get("id"),
                    "type": "response",
                    "command": "abort",
                    "success": True,
                }
            )
            return


if __name__ == "__main__":
    main()
