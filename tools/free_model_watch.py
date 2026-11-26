#!/usr/bin/env python3
"""Detect new and retired free models across every configured provider.

Why this exists: a free tier can vanish, a `:free` model can be retired, or a
gateway can serve a healthy `/models` catalogue from a stale token while every
completion returns 401. All three happened. A `/models` 200 is therefore not a
liveness test — the only one that counts is a minimal authenticated completion
per model, recording the code.

Output is a JSON catalogue per run plus a diff against the previous run, so
"new free model" and "retired model" are facts, not judgement calls.

Usage:
    python tools/free_model_watch.py                    # all providers, default caps
    python tools/free_model_watch.py --limit 20         # probe at most 20 per provider
    python tools/free_model_watch.py --provider kilo-gateway --limit 5
    python tools/free_model_watch.py --dry-run          # catalogue only, no probes

Exit codes: 0 ok, 1 new failures worth a look (dead free models), 2 config error.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROVIDERS_FILE = ROOT / "tools" / "providers.json"
OUT_DIR = ROOT / "tools" / "free-models"
PROBE_PROMPT = [{"role": "user", "content": "hi"}]


def load_env(paths: list[pathlib.Path]) -> dict[str, str]:
    """Read KEY=VALUE pairs from .env files without mutating os.environ."""
    env: dict[str, str] = {}
    for p in paths:
        if not p.exists():
            continue
        # binary-safe read: .env files here are CRLF and must not be rewritten
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def http(url: str, key: str | None, body: dict | None = None, timeout: int = 60) -> tuple[int | None, dict | str]:
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            # catalogues run to megabytes (kilo/openrouter); a truncated body
            # parses as a string and silently looks like "zero models"
            raw = r.read(8_000_000).decode("utf-8", "replace")
            try:
                return r.status, json.loads(raw)
            except Exception:
                return r.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read(4000).decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw
    except Exception as e:  # timeout, DNS, refused
        return None, f"{type(e).__name__}: {e}"


def list_models(provider: dict, key: str | None) -> tuple[int | None, list[str], str]:
    """Return (http_code, model_ids, note)."""
    url = provider["base_url"].rstrip("/") + provider.get("models_path", "/models")
    if provider.get("models_style") == "gemini":
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}key={key}"
        code, payload = http(url, None)
    else:
        code, payload = http(url, key)

    if not isinstance(payload, dict):
        return code, [], str(payload)[:160]

    ids: list[str] = []
    for m in payload.get("data") or payload.get("models") or []:
        if isinstance(m, dict):
            mid = m.get("id") or m.get("name") or ""
            if provider.get("models_style") == "gemini":
                mid = mid.replace("models/", "")
                # only chat-capable Gemini models
                methods = m.get("supportedGenerationMethods") or []
                if methods and "generateContent" not in methods:
                    continue
            if mid:
                ids.append(mid)
    return code, ids, ""


def classify(model_id: str, code: int | None, payload) -> str:
    """free / free-declared / paid / unknown — by evidence, not by hope."""
    declared = ":free" in model_id or model_id.endswith("-free")
    if code == 200 and isinstance(payload, dict):
        usage = payload.get("usage") or {}
        cost = usage.get("cost") if isinstance(usage, dict) else None
        if isinstance(cost, (int, float)) and cost > 0:
            return "paid"
        if declared:
            return "free-declared"
        return "free-unpriced" if cost in (0, None) else "paid"
    return "free-declared" if declared else "unknown"


def probe(provider: dict, key: str | None, model_id: str) -> dict:
    url = provider["base_url"].rstrip("/") + provider.get("chat_path", "/chat/completions")
    body = {
        "model": model_id,
        "messages": PROBE_PROMPT,
        "max_tokens": provider.get("probe_max_tokens", 1),
        "stream": False,
    }
    if provider.get("probe_extra"):
        body.update(provider["probe_extra"])
    code, payload = http(url, key, body)
    out = {"http_code": code, "status": "unknown", "detail": "", "class": "unknown"}
    if code == 200 and isinstance(payload, dict) and (payload.get("choices") or payload.get("candidates")):
        out["status"], out["class"] = "ok", classify(model_id, code, payload)
    elif code == 200:
        out["status"], out["detail"] = "empty", json.dumps(payload)[:120]
    elif code in (401, 403):
        out["status"], out["detail"] = "auth", str(payload)[:120]
    elif code == 404:
        out["status"], out["detail"] = "gone", str(payload)[:120]
    elif code == 429:
        out["status"], out["detail"] = "ratelimit", str(payload)[:120]
    elif code == 400:
        out["status"], out["detail"] = "bad-request", str(payload)[:120]
    elif code is None:
        out["status"], out["detail"] = "unreachable", str(payload)[:120]
    else:
        out["status"], out["detail"] = f"http-{code}", str(payload)[:120]
    return out


def summarise(prev: dict | None, curr: dict) -> list[str]:
    """Human diff: new free models, retired (or newly dead) ones."""
    lines: list[str] = []
    if not prev:
        lines.append("first run — no baseline to diff against")
        return lines
    prev_models = {(r["provider"], r["model_id"]): r for r in prev.get("models", [])}
    curr_models = {(r["provider"], r["model_id"]): r for r in curr.get("models", [])}

    new_free = [k for k, r in curr_models.items()
                if k not in prev_models and r["probe_status"] == "ok" and r["class"].startswith("free")]
    gone = [k for k in prev_models if k not in curr_models]
    dead = [k for k, r in curr_models.items()
            if k in prev_models and prev_models[k]["probe_status"] == "ok" and r["probe_status"] != "ok"]

    if new_free:
        lines.append(f"{len(new_free)} new usable free: " + ", ".join(f"{p}/{m}" for p, m in sorted(new_free)[:12]))
    if gone:
        lines.append(f"{len(gone)} delisted: " + ", ".join(f"{p}/{m}" for p, m in sorted(gone)[:12]))
    if dead:
        lines.append(f"{len(dead)} REGRESSED (worked last run, not now): " + ", ".join(f"{p}/{m}" for p, m in sorted(dead)[:12]))
    if not lines:
        lines.append("no change")
    return lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=25, help="max models probed per provider")
    ap.add_argument("--provider", action="append", help="only these providers (repeatable)")
    ap.add_argument("--dry-run", action="store_true", help="catalogue only, no completion probes")
    ap.add_argument("--out", default=str(OUT_DIR))
    ap.add_argument("--sleep", type=float, default=0.4, help="pause between probes, seconds")
    args = ap.parse_args()

    if not PROVIDERS_FILE.exists():
        print(f"missing {PROVIDERS_FILE}", file=sys.stderr)
        return 2
    providers = json.loads(PROVIDERS_FILE.read_text(encoding="utf-8"))["providers"]
    if args.provider:
        wanted = set(args.provider)
        providers = [p for p in providers if p["name"] in wanted]
        if not providers:
            print(f"no such provider: {sorted(wanted)}", file=sys.stderr)
            return 2

    env = load_env([ROOT / ".env", pathlib.Path.home() / "AppData/Local/hermes/.env"])
    out_dir = pathlib.Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    latest = out_dir / "latest.json"
    prev = json.loads(latest.read_text(encoding="utf-8")) if latest.exists() else None

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    records: list[dict] = []

    for p in providers:
        key = env.get(p["env_var"]) if p.get("env_var") else None
        if p.get("env_var") and not key:
            print(f"{p['name']}: no key in env ({p['env_var']}) — skipped", file=sys.stderr)
            records.append({"provider": p["name"], "model_id": "*", "class": "unknown",
                            "probe_status": "no-credential", "http_code": None, "detail": p["env_var"],
                            "checked_at": now})
            continue
        code, ids, note = list_models(p, key)
        print(f"{p['name']}: /models -> {code}, {len(ids)} models {('- ' + note) if note else ''}")
        if p.get("free_only_name_filter"):
            ids = [m for m in ids if p["free_only_name_filter"] in m]

        # Catalogue every model (cheap, no probe) so a retirement anywhere in the
        # list is detectable; probe only the free candidates and the first N, so
        # the checker does not become the rate limit it is measuring.
        probed = 0
        looks_free = ("free",)  # matched loosely: kilo-auto/free, :free, -free
        for mid in ids:
            rec = {"http_code": None, "status": "catalogued", "detail": "", "class": "unknown"}
            candidate = any(tok in mid.lower() for tok in looks_free)
            if not args.dry_run and probed < args.limit and (candidate or probed < (p.get("always_probe", 0) or 0)):
                rec = probe(p, key, mid)
                probed += 1
                time.sleep(args.sleep)
            elif candidate:
                rec["class"] = "free-declared"
            records.append({
                "provider": p["name"], "model_id": mid, "class": rec["class"],
                "probe_status": rec["status"], "http_code": rec["http_code"],
                "detail": rec["detail"][:160], "checked_at": now,
            })

    catalogue = {"generated_at": now, "dry_run": args.dry_run, "providers": [p["name"] for p in providers],
                 "models": records}
    stamp = now.replace(":", "").replace("-", "")
    body = json.dumps(catalogue, indent=2, sort_keys=True)
    (out_dir / f"{stamp}.json").write_text(body, encoding="utf-8")

    # A run that probed nothing must not become the baseline: everything would
    # look "regressed" on the next diff because no completion was attempted.
    probed_now = sum(1 for r in records if r["probe_status"] not in ("catalogued", "no-credential"))
    if probed_now:
        latest.write_text(body, encoding="utf-8")
    else:
        print("no probes this run - latest.json left untouched (it stays the diff baseline)")

    ok = sum(1 for r in records if r["probe_status"] == "ok")
    free_ok = sum(1 for r in records if r["probe_status"] == "ok" and r["class"].startswith("free"))
    dead_free = sum(1 for r in records if r["class"].startswith("free") and r["probe_status"] not in ("ok", "catalogued"))
    print(f"\n{ok} responding / {free_ok} usable free / {dead_free} declared-free but dead")
    for line in summarise(prev, catalogue):
        print("  " + line)
    return 1 if dead_free else 0


if __name__ == "__main__":
    sys.exit(main())
