#!/usr/bin/env python3
"""Conversa com o agente pelo terminal (sem WhatsApp) para testar antes da Parte 4.

Uso:  SERVICE_API_KEY=... python scripts/chat_cli.py [--base http://localhost:8000] [--phone "(11) 91234-5678"]
Digite mensagens como se fosse o cliente. Ctrl+C sai. Cria um negocio/lead de teste a cada execucao.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid


def call(base, key, method, path, body=None):
    req = urllib.request.Request(
        base + path, method=method, data=json.dumps(body).encode() if body is not None else None,
        headers={"X-API-Key": key, "content-type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code} em {path}: {e.read().decode()[:300]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--phone", default=None, help="telefone do 'cliente' (habilita supressao/opt-out)")
    ap.add_argument("--segment", default="barbearia")
    a = ap.parse_args()
    key = os.environ.get("SERVICE_API_KEY") or sys.exit("Defina SERVICE_API_KEY")
    biz = call(a.base, key, "POST", "/v1/businesses", {
        "name": f"Teste CLI {int(time.time())}", "segment": a.segment, "region": "teste",
        "address": f"Rua Teste {uuid.uuid4().hex[:6]}", "source": "manual",
    })
    lead = call(a.base, key, "POST", "/v1/leads", {"business_id": biz["id"]})
    print(f"Lead de teste: {lead['id']}  (Ctrl+C para sair)\n")
    try:
        while True:
            text = input("voce> ").strip()
            if not text:
                continue
            out = call(a.base, key, "POST", "/v1/agent/respond", {
                "lead_id": lead["id"], "text": text, "external_id": f"cli-{uuid.uuid4().hex}",
                "from_phone": a.phone,
            })
            print(f"[{out['action']}] {out.get('reply') or '(sem resposta)'}  {out['flags'] or ''}\n")
    except (KeyboardInterrupt, EOFError):
        print("\nate mais!")


if __name__ == "__main__":
    main()
