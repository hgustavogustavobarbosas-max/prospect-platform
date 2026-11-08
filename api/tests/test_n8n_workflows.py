"""Valida os JSONs de n8n/workflows (estrutura, conexoes, segredos, padroes de resiliencia)."""

import json
import re
from pathlib import Path

DIR = Path(__file__).resolve().parents[2] / "n8n" / "workflows"
FILES = sorted(DIR.glob("WF*.json"))
TRIGGERS = {
    "n8n-nodes-base.scheduleTrigger", "n8n-nodes-base.webhook", "n8n-nodes-base.errorTrigger",
    "n8n-nodes-base.manualTrigger",
}
ALLOWED_ENV = {"PROSPECT_API_URL", "PROSPECT_API_KEY", "N8N_WEBHOOK_SECRET", "NOTIFY_WEBHOOK_URL"}


def load():
    return [json.loads(f.read_text(encoding="utf-8")) for f in FILES]


def test_all_twelve_workflows_exist():
    names = {f.stem.split("_")[0] for f in FILES}
    assert names == {f"WF{i:02d}" for i in range(12)}


def test_structure_and_connections():
    for wf in load():
        names = [n["name"] for n in wf["nodes"]]
        assert len(names) == len(set(names)), wf["name"]
        ids = [n["id"] for n in wf["nodes"]]
        assert len(ids) == len(set(ids))
        for src, d in wf["connections"].items():
            assert src in names
            for slot in d["main"]:
                for c in slot:
                    assert c["node"] in names, (wf["name"], c["node"])
        assert wf["active"] is False  # nunca importar ativo sem revisao


def test_every_node_is_reachable_from_a_trigger():
    for wf in load():
        reach = {n["name"] for n in wf["nodes"] if n["type"] in TRIGGERS}
        assert reach, f"{wf['name']} sem trigger"
        changed = True
        while changed:
            changed = False
            for src in list(reach):
                for slot in wf["connections"].get(src, {}).get("main", []):
                    for c in slot:
                        if c["node"] not in reach:
                            reach.add(c["node"])
                            changed = True
        assert reach == {n["name"] for n in wf["nodes"]}, wf["name"]


def test_no_hardcoded_secrets_or_hosts_and_only_known_env_vars():
    for f in FILES:
        text = f.read_text(encoding="utf-8")
        assert "localhost" not in text and "127.0.0.1" not in text, f.name
        assert not re.search(r"(sk-|xoxb-|AIza)[A-Za-z0-9_-]{10,}", text), f.name
        for var in re.findall(r"\$env\.([A-Z0-9_]+)", text):
            assert var in ALLOWED_ENV, (f.name, var)


def test_error_workflow_is_wired_everywhere_except_itself():
    wfs = {w["name"]: w for w in load()}
    handler = next(w for n, w in wfs.items() if n.startswith("WF00"))
    for name, w in wfs.items():
        if name.startswith("WF00"):
            assert "errorWorkflow" not in w["settings"]
        else:
            assert w["settings"]["errorWorkflow"] == handler["id"], name


def test_http_nodes_retry_and_authenticate_against_the_api():
    for wf in load():
        for n in wf["nodes"]:
            if n["type"] != "n8n-nodes-base.httpRequest":
                continue
            p = n["parameters"]
            if "PROSPECT_API_URL" in p["url"]:
                hdr = {h["name"]: h["value"] for h in p["headerParameters"]["parameters"]}
                assert hdr["X-API-Key"] == "={{ $env.PROSPECT_API_KEY }}", (wf["name"], n["name"])
            assert n.get("retryOnFail") is True, (wf["name"], n["name"])
            assert n["parameters"]["options"]["timeout"] >= 30000


def test_inbound_webhook_checks_secret_before_calling_agent():
    wf = next(w for w in load() if w["name"].startswith("WF04"))
    conn = wf["connections"]
    first = conn["Mensagem recebida"]["main"][0][0]["node"]
    assert first == "Segredo valido?"
    assert conn["Segredo valido?"]["main"][0][0]["node"] == "Agente responde"
    assert conn["Segredo valido?"]["main"][1][0]["node"] == "Nao autorizado"


def test_outbox_enqueues_always_carry_an_idempotency_key():
    for wf in load():
        for n in wf["nodes"]:
            if n["type"] == "n8n-nodes-base.code" and "topic:" in n["parameters"]["jsCode"]:
                assert "idempotency_key" in n["parameters"]["jsCode"], (wf["name"], n["name"])
