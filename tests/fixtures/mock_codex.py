"""Deterministic mock of `codex exec` for adapter contract tests.

Configured via environment variables:

- ``MOCK_CODEX_TEXT``: content written to the -o last-message file for the
  first call (default: valid minimal InitialReviewResult JSON);
- ``MOCK_CODEX_REPAIR_TEXT``: content for subsequent calls;
- ``MOCK_CODEX_WRITE_PROBE=1``: the probe prompt makes the mock write
  probe.txt into the current directory (simulating an unsafe sandbox);
- ``MOCK_CODEX_FAIL=1``: exit non-zero with a stderr message.
"""

import os
import sys
from pathlib import Path


def main() -> int:
    reply = os.environ.get("MOCK_CODEX_TEXT", '{"issues": [], "summary": "mock"}')
    repair_reply = os.environ.get("MOCK_CODEX_REPAIR_TEXT", reply)
    write_probe = os.environ.get("MOCK_CODEX_WRITE_PROBE") == "1"
    fail = os.environ.get("MOCK_CODEX_FAIL") == "1"

    if fail:
        sys.stderr.write("mock codex failure\n")
        return 7

    args = sys.argv[1:]
    output_index = args.index("-o") + 1 if "-o" in args else None
    if output_index is None:
        sys.stderr.write("mock codex: no -o output file\n")
        return 8

    # Emit one JSONL event line on stdout (raw capture path).
    sys.stdout.write('{"type":"item.completed","item":{"type":"agent_message"}}\n')
    sys.stdout.flush()

    prompt = args[-1] if args else ""
    if prompt == "-":
        prompt = sys.stdin.read()
    is_repair = "Re-emit the same conclusion" in prompt
    text = repair_reply if is_repair else reply

    if "single word: OK" in prompt:
        text = "OK"

    if write_probe and "probe.txt" in prompt:
        Path("probe.txt").write_text("x", encoding="utf-8")
        text = "created probe.txt"

    Path(args[output_index]).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
