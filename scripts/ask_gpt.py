#!/usr/bin/env python3
"""GPT 연결 테스트 — 질문 하나를 보내고 응답을 findings/ 에 남긴다.

환경변수로 받는다: OPENAI_API_KEY(필수), QUESTION, MODEL.
Responses API(/v1/responses)를 쓴다 — GPT-5.6 계열은 OpenAI 문서가
Chat Completions 대신 이쪽을 권장한다.
표준 라이브러리만 쓴다. 실패해도 원인을 findings 파일에 적고 종료 코드는
0으로 둔다 — 커밋이 되어야 원격에서 실패 원인을 읽을 수 있다.
"""
from __future__ import annotations

import datetime
import json
import os
import pathlib
import urllib.error
import urllib.request

API_URL = "https://api.openai.com/v1/responses"
OUT = pathlib.Path("findings/gpt_test_response.md")


def extract_text(payload: dict) -> str:
    """Responses API 출력에서 텍스트를 뽑는다. 형태가 바뀔 수 있어 방어적으로."""
    if "output_text" in payload:
        return payload["output_text"]
    parts = []
    for item in payload.get("output", []):
        for c in item.get("content", []):
            if c.get("type") in ("output_text", "text"):
                parts.append(c.get("text", ""))
    return "\n".join(parts) if parts else json.dumps(payload, ensure_ascii=False, indent=2)


def main() -> int:
    question = os.environ.get("QUESTION") or "연결 테스트"
    model = os.environ.get("MODEL") or "gpt-5.6-sol"
    key = os.environ.get("OPENAI_API_KEY")
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    if not key:
        write(question, model, now, "실패", "OPENAI_API_KEY 가 비어 있다", None)
        return 0

    body = json.dumps({"model": model, "input": question}).encode("utf-8")
    req = urllib.request.Request(
        API_URL, data=body, method="POST",
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"})

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        answer = extract_text(payload)
        write(question, model, now, "성공", None, answer, payload)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        write(question, model, now, "실패", f"HTTP {exc.code}: {detail}", None)
    except Exception as exc:                          # noqa: BLE001
        write(question, model, now, "실패", str(exc), None)
    return 0


def write(question, model, now, status, error, answer, raw=None):
    OUT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# GPT 테스트 응답", "",
        f"- 시각(UTC): {now}", f"- 모델: {model}", f"- 상태: {status}", "",
        "## 질문", "", question, "",
    ]
    if status == "성공":
        lines += ["## 응답", "", answer, ""]
        if raw and "usage" in raw:
            lines += [f"- 토큰 사용: {raw['usage']}", ""]
    else:
        lines += ["## 오류", "", f"```\n{error}\n```", ""]
    OUT.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
