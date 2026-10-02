"""Call the local `claude` binary (Opus 5.5) and parse a JSON object back.

reason.py and generate.py both use this. Print mode, no session, Read tool
only when the prompt names frame images.
"""

import json
import os
import re
import subprocess

MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5-5")

SYSTEM = (
    "You look at image paths with the Read tool when the user lists them. "
    "Then you answer with one JSON object and no other text. "
    "Do not edit files, run commands, or fetch the web."
)


def parse_json(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


def call_claude(prompt, *, images=None, effort="low", budget=1.5, timeout=300, label="claude"):
    """Return the parsed JSON object from one `claude -p` call.

    `images` is a list of (caption, absolute path). The paths are already
    named in `prompt`; this flag only turns the Read tool on.
    """
    cmd = [
        "claude", "-p", prompt,
        "--model", MODEL,
        "--effort", effort,
        "--system-prompt", SYSTEM,
        "--output-format", "json",
        "--no-session-persistence",
        "--dangerously-skip-permissions",
        "--max-budget-usd", str(budget),
        "--tools", "Read" if images else "",
    ]
    print(f"  {label}: claude {MODEL} effort={effort} images={len(images or [])}", flush=True)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"{label} timed out after {timeout}s") from exc
    raw = proc.stdout or ""
    if proc.returncode != 0:
        tail = (proc.stderr or raw)[-800:]
        raise RuntimeError(f"{label} exited {proc.returncode}: {tail}")
    start = raw.find("{")
    if start < 0:
        raise RuntimeError(f"{label} returned no JSON envelope: {raw[:400]}")
    env = json.loads(raw[start:])
    if env.get("is_error"):
        raise RuntimeError(f"{label} error: {env.get('result')}")
    cost = env.get("total_cost_usd")
    if cost is not None:
        print(f"  {label}: ${cost:.3f}", flush=True)
    result = env.get("result", "")
    data = result if isinstance(result, dict) else parse_json(result)
    if not isinstance(data, dict):
        raise RuntimeError(f"{label} JSON was {type(data).__name__}, expected object")
    return data
