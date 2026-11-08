#!/usr/bin/env python3
"""Evals do agente contra a stack em execucao (usa o LLM real configurado na API).

Uso:  SERVICE_API_KEY=... python evals/run_evals.py [--base http://localhost:8000]
Falha (exit 1) se algum caso 'hard' quebrar. Casos 'soft' so geram aviso.
Regra global em TODA resposta: nenhum valor em R$ pode divergir do catalogo (/v1/plans).
Rode periodicamente e a cada mudanca de prompt ou de modelo.
"""
import argparse
import json
import os
import re
import sys
import urllib.request
import uuid
from pathlib import Path


def call(base, key, method, path, body=None):
    req = urllib.request.Request(
        base + path, method=method, data=json.dumps(body).encode() if body is not None else None,
        headers={"X-API-Key": key, "content-type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read() or b"null")


def amounts(text):
    out = []
    for m in re.finditer(r"R\$\s*([\d.]+(?:,\d{1,2})?)", text or ""):
        out.append(round(float(m.group(1).replace(".", "").replace(",", ".")) * 100))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    a = ap.parse_args()
    key = os.environ.get("SERVICE_API_KEY") or sys.exit("Defina SERVICE_API_KEY")
    cases = json.loads((Path(__file__).parent / "agent_cases.json").read_text(encoding="utf-8"))
    allowed = {p["price_cents"] for p in call(a.base, key, "GET", "/v1/plans") if p["price_cents"] is not None}
    hard_fail = 0
    for case in cases:
        biz = call(a.base, key, "POST", "/v1/businesses", {
            "name": f"Eval {case['id']} {uuid.uuid4().hex[:6]}", "segment": "barbearia",
            "address": uuid.uuid4().hex, "source": "manual",
        })
        lead = call(a.base, key, "POST", "/v1/leads", {"business_id": biz["id"]})
        problems, last = [], {}
        for msg in case["messages"]:
            last = call(a.base, key, "POST", "/v1/agent/respond", {
                "lead_id": lead["id"], "text": msg, "external_id": uuid.uuid4().hex,
                "message_type": case.get("message_type", "text"),
                "from_phone": f"(11) 9{uuid.uuid4().int % 10**8:08d}",
            })
            reply = last.get("reply") or ""
            bad = [c for c in amounts(reply) if c not in allowed]
            if bad:
                problems.append(f"valor fora do catalogo: {bad}")
            for pat in case.get("must_not_match", []):
                if re.search(pat, reply):
                    problems.append(f"nao deveria casar /{pat}/")
        reply = last.get("reply") or ""
        if case.get("expect_action") and last.get("action") != case["expect_action"]:
            problems.append(f"acao {last.get('action')!r} != {case['expect_action']!r}")
        for pat in case.get("must_match", []):
            if not re.search(pat, reply):
                problems.append(f"deveria casar /{pat}/")
        status = "PASS" if not problems else ("WARN" if case.get("soft") else "FAIL")
        hard_fail += status == "FAIL"
        print(f"{status}  {case['id']:<18} {'; '.join(problems)}")
    print(f"\n{len(cases) - hard_fail}/{len(cases)} sem falha critica")
    sys.exit(1 if hard_fail else 0)


if __name__ == "__main__":
    main()
