#!/usr/bin/env python3
"""Call the external critic (OpenAI) on a phase report and write CRITIQUE files.

Usage:
    python scripts/critique.py --phase P1 --input REPORT_P1.md
    python scripts/critique.py --phase P1 --input FACTS.md --round 2
    python scripts/critique.py --from-request REVIEW_REQUEST.md

Outputs (under review/):
    CRITIQUE_<TAG>_r<N>.json   machine-readable, consumed by gate.py
    CRITIQUE_<TAG>_r<N>.md     human-readable
    PROMPT_<TAG>_r<N>.md       exact prompt sent, kept as evidence

Environment:
    OPENAI_API_KEY   required
    OPENAI_MODEL     required (no default -- pin it deliberately and record it)
    OPENAI_BASE_URL  optional
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PROMPT_DIR = ROOT / "prompts"
REVIEW_DIR = ROOT / "review"

MAX_ITEMS = 7          # items carrying a response obligation
MAX_ROUNDS = 2
MIN_IMPACT_CHARS = 30  # shorter than this is not a real impact statement

VALID_PHASES = ("P0", "P1", "P2", "P3", "M")


def read(path: pathlib.Path) -> str:
    if not path.exists():
        sys.exit(f"[critique] missing file: {path}")
    return path.read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# REVIEW_REQUEST.md header

def parse_request(path: pathlib.Path) -> dict:
    """Read the yaml-ish header block from a REVIEW_REQUEST.md."""
    text = read(path)
    m = re.search(r"```yaml\n(.*?)```", text, re.S)
    if not m:
        sys.exit(f"[critique] {path} has no yaml header block")
    meta: dict = {}
    key = None
    for line in m.group(1).splitlines():
        line = line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if line.startswith("  - "):
            if key:
                meta.setdefault(key, []).append(line[4:].strip())
        elif ":" in line:
            k, v = line.split(":", 1)
            key, v = k.strip(), v.strip()
            if v:
                meta[key] = int(v) if v.isdigit() else v
                key = None
    for req in ("phase", "tag", "inputs"):
        if req not in meta:
            sys.exit(f"[critique] {path} header is missing '{req}'")
    return meta


# --------------------------------------------------------------------------
# prompt assembly

def build_prompt(phase: str, tag: str, inputs: list[pathlib.Path],
                 round_no: int, context: list[pathlib.Path]) -> str:
    parts = [read(PROMPT_DIR / "_common.md"),
             read(PROMPT_DIR / f"critique_{phase}.md")]

    if round_no > 1:
        prior = REVIEW_DIR / f"RESPONSE_{tag}_r{round_no - 1}.md"
        parts.append(
            "# 2\ub77c\uc6b4\ub4dc \uc9c0\uc2dc\n\n"
            "\uc544\ub798\ub294 1\ub77c\uc6b4\ub4dc \ube44\ud3c9\uc5d0 \ub300\ud55c \uc800\uc790\uc758 \uc751\ub2f5\uc774\ub2e4. \uaddc\uce59:\n\n"
            "- \uc774\ubbf8 \ud310\uc815\ub41c \ud56d\ubaa9\uc744 \ub2e4\uc2dc \uc81c\uae30\ud558\uc9c0 \ub9c8\ub77c. \uc800\uc790\uc758 \ubc18\ubc15\uc774 \ubd88\ucda9\ubd84\ud558\ub2e4\uace0\n"
            "  \ud310\ub2e8\ud558\ub294 \uacbd\uc6b0\uc5d0\ub9cc, **\ubc18\ubc15\uc758 \uc5b4\ub290 \ubd80\ubd84\uc774 \uc65c \ubd88\ucda9\ubd84\ud55c\uc9c0**\ub97c \uc9c0\ubaa9\ud558\uc5ec\n"
            "  \uc81c\uae30\ud558\ub77c. \ub2e8\uc21c \ubc18\ubcf5\uc740 \uae08\uc9c0\ub2e4.\n"
            "- \uc800\uc790\uac00 '\uc218\uc815'\uc73c\ub85c \ud310\uc815\ud55c \ud56d\ubaa9\uc740 \ub2e4\ub8e8\uc9c0 \ub9c8\ub77c. \uc218\uc815\ub41c \ubb38\uc11c\ub294 \ub2e4\uc74c\n"
            "  \ub2e8\uacc4\uc5d0\uc11c \ub2e4\uc2dc \uac80\ud1a0\ub41c\ub2e4.\n"
            "- \uc751\ub2f5\uc744 \uc77d\uace0 \uc0c8\ub85c \ubcf4\uc774\uac8c \ub41c \ubb38\uc81c\uac00 \uc788\uc73c\uba74 \uadf8\uac83\uc744 \uc6b0\uc120\ud558\ub77c.\n"
            "- 2\ub77c\uc6b4\ub4dc\uac00 \ub9c8\uc9c0\ub9c9\uc774\ub2e4. \ub0a8\uae38 \uac00\uce58\uac00 \uc788\ub294 \uac83\ub9cc \ub0a8\uaca8\ub77c.\n\n"
            "## \uc800\uc790\uc758 1\ub77c\uc6b4\ub4dc \uc751\ub2f5\n\n" + read(prior))

    for p in context:
        parts.append(f"# \ucc38\uace0 \ubb38\uc11c: {p.name}\n\n{read(p)}")

    for p in inputs:
        parts.append(f"# \uac80\ud1a0 \ub300\uc0c1 \ubb38\uc11c: {p.name}\n\n{read(p)}")

    return "\n\n---\n\n".join(parts)


# --------------------------------------------------------------------------
# API call

def call_openai(prompt: str, model: str) -> tuple[str, str]:
    """Return (raw_json_text, api_used).

    Newer OpenAI models are served through the Responses API; older ones only
    through Chat Completions. Rather than make the caller find out which, try
    Responses first and fall back. The API actually used is recorded in the
    critique payload, because a change of endpoint can change output shape and
    is therefore part of the record.
    """
    try:
        from openai import OpenAI
    except ImportError:
        sys.exit("[critique] pip install openai")

    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        sys.exit("[critique] OPENAI_API_KEY is not set")

    kwargs = {"api_key": key}
    if os.environ.get("OPENAI_BASE_URL"):
        kwargs["base_url"] = os.environ["OPENAI_BASE_URL"]
    client = OpenAI(**kwargs)

    system = ("You are an adversarial external referee for an empirical "
              "research project. Answer in Korean. Output a single JSON "
              "object and nothing else.")
    failures: list[str] = []

    # 1. Responses API
    try:
        resp = client.responses.create(
            model=model,
            input=[{"role": "system", "content": system},
                   {"role": "user", "content": prompt}],
            text={"format": {"type": "json_object"}},
        )
        text = getattr(resp, "output_text", "") or ""
        if text.strip():
            return text, "responses"
        failures.append("responses: empty output_text")
    except Exception as exc:                          # noqa: BLE001
        failures.append(f"responses: {type(exc).__name__}: {exc}")

    # 2. Chat Completions
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        text = resp.choices[0].message.content or ""
        if text.strip():
            return text, "chat.completions"
        failures.append("chat.completions: empty content")
    except Exception as exc:                          # noqa: BLE001
        failures.append(f"chat.completions: {type(exc).__name__}: {exc}")

    sys.exit("[critique] every API path failed for model "
             f"{model!r}:\n  - " + "\n  - ".join(failures) +
             "\n\nCheck that OPENAI_MODEL names a model this key can reach:\n"
             "  curl -s https://api.openai.com/v1/models "
             '-H "Authorization: Bearer $OPENAI_API_KEY"')


# --------------------------------------------------------------------------
# post-processing: enforce the rules the prompt asked for

def parse_items(raw: str) -> list[dict]:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        sys.exit(f"[critique] model did not return valid JSON: {exc}\n---\n{text[:2000]}")

    items = data.get("items")
    if not isinstance(items, list):
        sys.exit("[critique] JSON has no 'items' array")
    return items


def enforce(items: list[dict]) -> tuple[list[dict], list[dict]]:
    """Return (binding, advisory). Demotion is one-way: we never promote."""
    fields = ("title", "claim", "evidence_in_report", "impact", "suggested_check")
    binding, advisory = [], []

    for i, it in enumerate(items, 1):
        rec = {k: str(it.get(k, "")).strip() for k in fields}
        rec["id"] = str(it.get("id") or f"K{i}").strip()
        rec["requires_author_decision"] = bool(it.get("requires_author_decision", False))
        declared = str(it.get("severity", "")).strip()

        # An item without a substantive impact statement cannot bind.
        if len(rec["impact"]) < MIN_IMPACT_CHARS or declared == "\uc0ac\uc18c":
            rec["severity"] = "\uc0ac\uc18c"
            rec["demoted"] = declared == "\ud575\uc2ec"
            advisory.append(rec)
        else:
            rec["severity"] = "\ud575\uc2ec"
            rec["demoted"] = False
            binding.append(rec)

    # Cap the response obligation; the overflow stays visible but advisory.
    if len(binding) > MAX_ITEMS:
        overflow = binding[MAX_ITEMS:]
        for rec in overflow:
            rec["severity"] = "\uc0ac\uc18c"
            rec["overflow"] = True
        advisory = overflow + advisory
        binding = binding[:MAX_ITEMS]

    # Renumber so ids are stable and unique across the two lists.
    for n, rec in enumerate(binding, 1):
        rec["id"] = f"K{n}"
    for n, rec in enumerate(advisory, 1):
        rec["id"] = f"A{n}"

    return binding, advisory


def render_md(tag: str, round_no: int, model: str,
              binding: list[dict], advisory: list[dict]) -> str:
    ts = _dt.datetime.now().isoformat(timespec="seconds")
    out = [f"# CRITIQUE {tag} \u2014 round {round_no}", "",
           f"- \uc0dd\uc131: {ts}", f"- \ubaa8\ub378: {model}",
           f"- \ud310\uc815 \uc758\ubb34 \ud56d\ubaa9: {len(binding)}\uac1c",
           f"- \ucc38\uace0 \ud56d\ubaa9(\ud310\uc815 \ubd88\uc694): {len(advisory)}\uac1c", "",
           f"`review/RESPONSE_{tag}_r{round_no}.md`\uc5d0 \uc544\ub798 K \ud56d\ubaa9 \uc804\ubd80\uc5d0 \ub300\ud55c "
           "\ud310\uc815\uc744 \uc791\uc131\ud574\uc57c \ub2e4\uc74c \ub2e8\uacc4\uac00 \uc5f4\ub9bd\ub2c8\ub2e4.", "",
           "---", ""]

    if not binding:
        out += ["## \ud310\uc815 \uc758\ubb34 \ud56d\ubaa9", "", "\uc5c6\uc74c. \uac8c\uc774\ud2b8\ub294 \uc790\ub3d9 \ud1b5\uacfc\ud569\ub2c8\ub2e4.", ""]
    else:
        out += ["## \ud310\uc815 \uc758\ubb34 \ud56d\ubaa9", ""]
        for rec in binding:
            flag = " \u00b7 \uc800\uc790 \ud310\ub2e8 \ud544\uc694" if rec["requires_author_decision"] else ""
            out += [f"### {rec['id']} \u2014 {rec['title']}{flag}", "",
                    f"**\uc9c0\uc801.** {rec['claim']}", "",
                    f"**\ubb38\uc11c \uadfc\uac70.** {rec['evidence_in_report']}", "",
                    f"**\ud30c\uae09.** {rec['impact']}", "",
                    f"**\ud655\uc778 \ubc29\ubc95.** {rec['suggested_check']}", ""]

    if advisory:
        out += ["---", "", "## \ucc38\uace0 \ud56d\ubaa9 (\ud310\uc815 \ubd88\uc694)", ""]
        for rec in advisory:
            note = []
            if rec.get("demoted"):
                note.append("\ud30c\uae09 \uc9c4\uc220 \ubbf8\ub2ec\ub85c \uac15\ub4f1")
            if rec.get("overflow"):
                note.append(f"\uc0c1\ud55c {MAX_ITEMS}\uac1c \ucd08\uacfc")
            suffix = f"  _({'; '.join(note)})_" if note else ""
            out += [f"- **{rec['id']}** {rec['title']}{suffix}",
                    f"  - {rec['claim']}", ""]

    return "\n".join(out)


# --------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=VALID_PHASES)
    ap.add_argument("--milestone", help="e.g. M2 -- required when --phase M")
    ap.add_argument("--input", nargs="+", help="documents under review")
    ap.add_argument("--context", nargs="*", default=[], help="reference docs")
    ap.add_argument("--round", type=int, default=1)
    ap.add_argument("--from-request", help="REVIEW_REQUEST.md; supplies phase/tag/round/inputs")
    ap.add_argument("--emit-json-only", action="store_true",
                    help="print the payload to stdout for CI validation")
    args = ap.parse_args()

    if args.from_request:
        meta = parse_request(pathlib.Path(args.from_request))
        args.phase = meta["phase"]
        args.milestone = meta.get("tag") if meta["phase"] == "M" else None
        args.round = meta.get("round", 1)
        args.input = meta["inputs"]
        args.context = meta.get("context", []) + [args.from_request]

    if not args.phase or not args.input:
        sys.exit("[critique] need --phase and --input, or --from-request")
    if args.phase == "M" and not args.milestone:
        sys.exit("[critique] --phase M requires --milestone")
    if not 1 <= args.round <= MAX_ROUNDS:
        sys.exit(f"[critique] round must be 1..{MAX_ROUNDS}")

    model = os.environ.get("OPENAI_MODEL")
    if not model:
        sys.exit("[critique] OPENAI_MODEL is not set. Pin the model explicitly; "
                 "the choice is part of the record.")

    tag = args.milestone if args.phase == "M" else args.phase
    REVIEW_DIR.mkdir(exist_ok=True)

    if args.round > 1:
        prior = REVIEW_DIR / f"RESPONSE_{tag}_r{args.round - 1}.md"
        if not prior.exists():
            sys.exit(f"[critique] round {args.round} needs {prior}")

    inputs = [pathlib.Path(p) for p in args.input]
    context = [pathlib.Path(p) for p in args.context]

    prompt = build_prompt(args.phase, tag, inputs, args.round, context)
    (REVIEW_DIR / f"PROMPT_{tag}_r{args.round}.md").write_text(prompt, encoding="utf-8")

    print(f"[critique] {tag} round {args.round} -> {model} "
          f"({len(prompt):,} chars)", file=sys.stderr)

    raw, api_used = call_openai(prompt, model)
    binding, advisory = enforce(parse_items(raw))
    print(f"[critique] api={api_used}", file=sys.stderr)

    payload = {
        "tag": tag, "phase": args.phase, "round": args.round, "model": model,
        "api": api_used,
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "inputs": [str(p) for p in inputs],
        "binding": binding, "advisory": advisory,
    }
    (REVIEW_DIR / f"CRITIQUE_{tag}_r{args.round}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.emit_json_only:
        print(json.dumps(payload, ensure_ascii=False))
    (REVIEW_DIR / f"CRITIQUE_{tag}_r{args.round}.md").write_text(
        render_md(tag, args.round, model, binding, advisory), encoding="utf-8")

    print(f"[critique] {len(binding)} binding, {len(advisory)} advisory", file=sys.stderr)
    print(f"[critique] wrote review/CRITIQUE_{tag}_r{args.round}.md", file=sys.stderr)
    if binding:
        print(f"[critique] NEXT: write review/RESPONSE_{tag}_r{args.round}.md", file=sys.stderr)


if __name__ == "__main__":
    main()
