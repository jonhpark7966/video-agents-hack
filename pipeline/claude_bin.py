"""Call Cosmos Reason on this VAST instance and parse a JSON object back.

reason.py and generate.py both use this. The temporal branch talked to a local
`claude` binary; this instance has Cosmos3-Reason on the shared GPU endpoint,
and the sample clip is already indexed in VSS.
"""

import base64
import json
import os
import re
import urllib.error
import urllib.request

MODEL = os.environ.get("COSMOS3_REASON_MODEL", "nvidia/cosmos3-nano-reasoner")
COSMOS_URL = os.environ.get("COSMOS3_REASON_URL", "http://166.19.38.112:8001")

SYSTEM = (
    "You answer with one JSON object and no other text. "
    "When images are attached, look at them in the order given. "
    "Do not refuse, and do not wrap the JSON in markdown."
)


def ensure_env():
    if os.environ.get("GPU_BEARER_TOKEN") and os.environ.get("INGRESS_URL"):
        return
    configs = sorted(
        name for name in os.listdir("/config")
        if name.endswith(".config")
    ) if os.path.isdir("/config") else []
    if len(configs) != 1:
        return
    with open(os.path.join("/config", configs[0])) as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def parse_json(text):
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


def _post(url, payload, timeout):
    ensure_env()
    token = os.environ.get("GPU_BEARER_TOKEN", "")
    if not token:
        raise RuntimeError("GPU_BEARER_TOKEN is not set")
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        raise RuntimeError(f"Cosmos HTTP {exc.code}: {detail}") from exc


def _model():
    global MODEL
    if os.environ.get("COSMOS3_REASON_MODEL"):
        return os.environ["COSMOS3_REASON_MODEL"]
    ensure_env()
    token = os.environ.get("GPU_BEARER_TOKEN", "")
    req = urllib.request.Request(
        COSMOS_URL.rstrip("/") + "/v1/models",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            body = json.load(response)
        MODEL = body["data"][0]["id"]
        os.environ["COSMOS3_REASON_MODEL"] = MODEL
    except Exception:
        pass
    return MODEL


def call_claude(prompt, *, images=None, effort="low", budget=1.5, timeout=180, label="cosmos"):
    """Return one JSON object from Cosmos Reason.

    `images` is a list of (caption, absolute path). They are attached in order.
    The name stays `call_claude` so the loop's draft and grade steps do not change.
    """
    model = _model()
    content = [{"type": "text", "text": prompt}]
    if images:
        content[0]["text"] = (
            prompt
            + "\n\nThe frames are attached next, in the same order as the list above. "
            "Judge the pictures, not the file paths."
        )
        for _caption, path in images:
            raw = open(path, "rb").read()
            encoded = base64.b64encode(raw).decode()
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
            })
    max_tokens = 2200 if effort == "medium" else 1400
    print(f"  {label}: cosmos {model} images={len(images or [])}", flush=True)
    body = _post(
        COSMOS_URL.rstrip("/") + "/v1/chat/completions",
        {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": content if images else prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.1,
        },
        timeout,
    )
    message = body["choices"][0]["message"]
    text = message.get("content") or message.get("reasoning_content") or ""
    data = text if isinstance(text, dict) else parse_json(text)
    if not isinstance(data, dict):
        raise RuntimeError(f"{label} JSON was {type(data).__name__}, expected object")
    return data
