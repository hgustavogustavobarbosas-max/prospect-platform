"""Laco de tool calling (puro): o LLM e o executor de ferramentas sao injetados."""

import json
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class ChatResponse:
    blocks: list[dict]
    stop_reason: str
    tokens: int


def run_llm(
    llm,
    *,
    system: str,
    messages: list[dict],
    tools: list[dict],
    execute: Callable[[str, dict], dict],
    max_iterations: int = 3,
    max_tokens: int = 500,
    before_request: Callable[[dict], None] | None = None,
) -> tuple[str, int, list[str]]:
    """Retorna (texto, tokens_totais, nomes_das_ferramentas_chamadas)."""
    msgs = list(messages)
    total, called = 0, []
    for _ in range(max_iterations):
        kwargs = {}
        if before_request:
            payload = {"system": system, "messages": msgs, "tools": tools}
            kwargs["before_request"] = lambda payload=payload: before_request(payload)
        resp: ChatResponse = llm.chat(
            system=system, messages=msgs, tools=tools, max_tokens=max_tokens, **kwargs
        )
        total += resp.tokens
        if resp.stop_reason == "tool_use":
            msgs.append({"role": "assistant", "content": resp.blocks})
            results = []
            for b in resp.blocks:
                if b.get("type") == "tool_use":
                    called.append(b["name"])
                    out = execute(b["name"], b.get("input") or {})
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": b["id"],
                            "content": json.dumps(out, ensure_ascii=False),
                        }
                    )
            msgs.append({"role": "user", "content": results})
            continue
        text = "".join(b.get("text", "") for b in resp.blocks if b.get("type") == "text").strip()
        return text, total, called
    return "", total, called  # excedeu as iteracoes: o chamador usa o fallback


def build_history(rows: list[tuple[str, str]], limit: int) -> list[dict]:
    """rows = [(direction, content)] em ordem cronologica. Funde papeis repetidos e comeca em 'user'."""
    out: list[dict] = []
    for direction, content in rows[-limit:]:
        role = "user" if direction == "in" else "assistant"
        if not content:
            continue
        if out and out[-1]["role"] == role:
            out[-1]["content"] += "\n" + content
        else:
            out.append({"role": role, "content": content})
    while out and out[0]["role"] != "user":
        out.pop(0)
    return out
