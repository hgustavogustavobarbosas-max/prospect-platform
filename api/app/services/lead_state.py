"""Maquina de estados do lead: a unica fonte da verdade do funil fica no Postgres."""

TRANSITIONS: dict[str, set[str]] = {
    "new": {"qualified", "lost", "suppressed"},
    "qualified": {"contacted", "lost", "suppressed"},
    "contacted": {"replying", "lost", "suppressed"},
    "replying": {"handoff", "lost", "suppressed"},
    "handoff": {"won", "lost", "suppressed"},
    "won": set(),
    "lost": set(),
    "suppressed": set(),
}


def can_transition(current: str, new: str) -> bool:
    return new in TRANSITIONS.get(current, set())


def find_path(current: str, target: str) -> list[str] | None:
    """Menor sequencia de transicoes validas current -> target (BFS). [] se ja esta la."""
    if current == target:
        return []
    queue = [(current, [])]
    seen = {current}
    while queue:
        node, path = queue.pop(0)
        for nxt in sorted(TRANSITIONS.get(node, set())):
            if nxt in seen:
                continue
            if nxt == target:
                return [*path, nxt]
            seen.add(nxt)
            queue.append((nxt, [*path, nxt]))
    return None
