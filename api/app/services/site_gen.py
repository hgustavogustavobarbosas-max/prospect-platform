"""Geracao do site: previa (noindex, temporaria) e pacote final (SEO, deploy). Tudo escapado."""

import html
import io
import json
import re
import zipfile

DEFAULT_COLOR = "#1f5fa8"
SEGMENT_COPY = {
    "barbearia": ("Barbearia", "Agende seu horario", "Cortes, barba e cuidado masculino"),
    "estetica": ("Estetica", "Agende sua avaliacao", "Cuidados com a sua beleza e bem-estar"),
}


def _e(v) -> str:
    return html.escape(str(v or ""), quote=True)


def _color(v: str | None) -> str:
    return v if v and re.fullmatch(r"#[0-9a-fA-F]{6}", v) else DEFAULT_COLOR


def _digits(v: str | None) -> str:
    return re.sub(r"\D", "", v or "")


def render_site(data: dict, *, preview: bool, domain: str | None = None) -> str:
    seg_key = next((k for k in SEGMENT_COPY if k in (data.get("segmento") or "").lower()), None)
    seg_label, cta, tagline = SEGMENT_COPY.get(seg_key, ("Seu negocio", "Fale conosco", "Atendimento de qualidade"))
    name = data.get("nome_negocio") or seg_label
    color = _color(data.get("cor_principal"))
    city = data.get("cidade") or ""
    services = [s for s in (data.get("servicos") or []) if str(s).strip()][:12]
    wa = _digits(data.get("whatsapp") or data.get("telefone"))
    desc = data.get("descricao") or tagline
    url = f"https://{domain}/" if domain else ""

    robots = '<meta name="robots" content="noindex, nofollow">' if preview else '<meta name="robots" content="index, follow">'
    seo = ""
    if not preview:
        ld = {
            "@context": "https://schema.org", "@type": "LocalBusiness", "name": name,
            "description": desc, "telephone": data.get("telefone") or "",
            "address": {"@type": "PostalAddress", "streetAddress": data.get("endereco") or "", "addressLocality": city},
            "url": url,
        }
        seo = (
            (f'<link rel="canonical" href="{_e(url)}">\n' if url else "")
            + f'<meta property="og:title" content="{_e(name)}">\n<meta property="og:description" content="{_e(desc)}">\n'
            + '<script type="application/ld+json">' + json.dumps(ld, ensure_ascii=False).replace("</", "<\\/") + "</script>"
        )
    banner = (
        '<div class="pv">Previa de demonstracao - nao e o site final</div>' if preview else ""
    )
    items = "".join(f"<li>{_e(s)}</li>" for s in services) or "<li>Entre em contato para conhecer nossos servicos</li>"
    button = f'<a class="btn" href="https://wa.me/{wa}">{_e(cta)}</a>' if wa else ""
    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(name)}{' - ' + _e(city) if city else ''}</title>
<meta name="description" content="{_e(desc)[:155]}">
{robots}
{seo}
<style>
:root{{--c:{color}}} *{{box-sizing:border-box}} body{{margin:0;font-family:system-ui,sans-serif;color:#1d1d1f;line-height:1.5}}
header{{background:var(--c);color:#fff;padding:48px 20px;text-align:center}} h1{{margin:0 0 8px;font-size:2rem}}
main{{max-width:760px;margin:0 auto;padding:24px 20px}} h2{{color:var(--c)}} ul{{padding-left:20px}}
.btn{{display:inline-block;background:#fff;color:var(--c);padding:12px 22px;border-radius:8px;font-weight:700;text-decoration:none;margin-top:12px}}
footer{{padding:24px;text-align:center;color:#666;font-size:.9rem}} .pv{{background:#fff3cd;padding:8px;text-align:center;font-size:.85rem}}
</style></head><body>{banner}
<header><h1>{_e(name)}</h1><p>{_e(tagline)}</p>{button}</header>
<main><h2>Sobre</h2><p>{_e(desc)}</p><h2>Servicos</h2><ul>{items}</ul>
<h2>Contato</h2><p>{_e(data.get('endereco'))}<br>{_e(data.get('horario'))}<br>{_e(data.get('telefone'))}</p></main>
<footer>&copy; {_e(name)}</footer></body></html>"""


def build_package(data: dict, *, domain: str | None) -> bytes:
    """Repositorio base do site final: HTML, SEO (robots/sitemap), Lighthouse CI e guia de deploy."""
    host = domain or "SEU-DOMINIO.com.br"
    files = {
        "index.html": render_site(data, preview=False, domain=domain),
        "404.html": "<!doctype html><meta charset=utf-8><title>Pagina nao encontrada</title><h1>Pagina nao encontrada</h1><a href='/'>Voltar</a>",
        "robots.txt": f"User-agent: *\nAllow: /\nSitemap: https://{host}/sitemap.xml\n",
        "sitemap.xml": (
            '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f"  <url><loc>https://{host}/</loc></url>\n</urlset>\n"
        ),
        "lighthouserc.json": json.dumps(
            {"ci": {"collect": {"staticDistDir": "."}, "assert": {"assertions": {
                "categories:performance": ["warn", {"minScore": 0.9}],
                "categories:seo": ["error", {"minScore": 0.9}],
                "categories:accessibility": ["warn", {"minScore": 0.9}],
            }}}}, indent=2),
        ".github/workflows/lighthouse.yml": (
            "name: lighthouse\non: [push]\njobs:\n  lh:\n    runs-on: ubuntu-latest\n    steps:\n"
            "      - uses: actions/checkout@v4\n      - run: npx --yes @lhci/cli@0.14 autorun\n"
        ),
        "README_DEPLOY.md": (
            f"# Deploy do site\n\n1. Crie um repositorio com estes arquivos.\n"
            "2. Hospedagem gratuita: Cloudflare Pages ou Vercel (pasta raiz `.`, sem build).\n"
            f"3. Dominio: aponte `{host}` conforme as instrucoes da hospedagem (CNAME/A) e ative HTTPS.\n"
            "4. Confira: `robots.txt`, `sitemap.xml`, titulo/descricao e o botao de WhatsApp.\n"
            "5. Cadastre o site no Google Search Console e envie o sitemap.\n"
            "6. Registre a URL final no CRM (`POST /v1/opportunities/{id}/deliver`) para ativar o monitoramento.\n"
        ),
        "OFFBOARDING.md": (
            "# Checklist de encerramento\n- [ ] Cliente tem acesso ao dominio e a hospedagem\n"
            "- [ ] Repositorio transferido\n- [ ] Credenciais rotacionadas\n- [ ] Backup final entregue\n"
            "- [ ] Dados do cliente excluidos do CRM (se solicitado)\n"
        ),
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in files.items():
            z.writestr(name, content)
    return buf.getvalue()
