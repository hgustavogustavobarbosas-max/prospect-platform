"""Classificacao e verificacao de sites. Inclui protecao contra SSRF."""

import ipaddress
import socket
from urllib.parse import urljoin, urlparse

SOCIAL_HOSTS = {
    "instagram.com", "facebook.com", "fb.com", "linktr.ee", "linktree.com", "beacons.ai",
    "wa.me", "whatsapp.com", "tiktok.com", "bio.link", "booksy.com", "ifood.com.br",
}
BOT_BLOCK_CODES = {401, 403, 405, 429, 999}  # protecao anti-bot: o site existe


def _host(url: str) -> str:
    u = url.strip()
    if "://" not in u:
        u = "https://" + u
    return (urlparse(u).hostname or "").lower().removeprefix("www.")


def classify_url(url: str | None) -> str:
    """'none' (sem site) | 'social' (so rede social/agregador) | 'site'."""
    if not url or not url.strip():
        return "none"
    host = _host(url)
    if not host:
        return "none"
    for h in SOCIAL_HOSTS:
        if host == h or host.endswith("." + h):
            return "social"
    return "site"


def is_public_host(host: str) -> bool:
    """False se o host resolver para IP privado/loopback/link-local (anti-SSRF)."""
    if not host:
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for info in infos:
        addr = info[4][0].split("%")[0]
        try:
            if not ipaddress.ip_address(addr).is_global:
                return False
        except ValueError:
            return False
    return True


def check_site(url: str, *, timeout: float = 5.0, max_redirects: int = 3, http=None) -> str:
    """'site_ok' | 'site_down' | 'unchecked' (host inseguro). Nao baixa o corpo da resposta.

    Limite conhecido: entre a resolucao DNS e a conexao existe uma janela (DNS rebinding).
    Rode o container sem acesso a redes internas para defesa em profundidade.
    """
    import httpx

    current = url if "://" in url else "https://" + url
    client = http or httpx.Client(timeout=timeout, follow_redirects=False)
    headers = {"User-Agent": "ProspectBot/0.1 (verificacao de presenca digital)"}
    try:
        for _ in range(max_redirects + 1):
            parsed = urlparse(current)
            if parsed.scheme not in ("http", "https") or not is_public_host(parsed.hostname or ""):
                return "unchecked"
            try:
                with client.stream("GET", current, headers=headers) as resp:
                    code = resp.status_code
                    location = resp.headers.get("location")
            except httpx.HTTPError:
                return "site_down"
            if code in (301, 302, 303, 307, 308) and location:
                current = urljoin(current, location)
                continue
            return "site_ok" if code < 400 or code in BOT_BLOCK_CODES else "site_down"
        return "site_down"  # redirecionamentos demais
    finally:
        if http is None:
            client.close()
