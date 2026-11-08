"""Paginas HTML publicas (links com token). Todo dado dinamico e escapado."""

import html

_CSS = (
    "body{font-family:system-ui,sans-serif;max-width:640px;margin:32px auto;padding:0 16px;line-height:1.5;color:#1d1d1f}"
    "h1{color:#1f5fa8}button,.b{background:#1f5fa8;color:#fff;border:0;padding:12px 20px;border-radius:8px;font-size:1rem;cursor:pointer;text-decoration:none;display:inline-block}"
    "input,textarea,select{width:100%;padding:10px;margin:4px 0 14px;border:1px solid #ccc;border-radius:6px;font:inherit}"
    "label{font-weight:600}.card{border:1px solid #ddd;border-radius:10px;padding:16px;margin:16px 0}"
)


def e(v) -> str:
    return html.escape(str(v if v is not None else ""), quote=True)


def page(title: str, body: str) -> str:
    return (
        f"<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'>"
        f"<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<meta name='robots' content='noindex, nofollow'><title>{e(title)}</title><style>{_CSS}</style></head>"
        f"<body>{body}</body></html>"
    )


def proposal_page(*, agency, plan_name, price_text, valid_until, features, pdf_url, accept_url, accepted, expired) -> str:
    feats = "".join(f"<li>{e(f)}</li>" for f in features)
    action = (
        "<p><strong>Proposta aceita. Obrigado!</strong></p>" if accepted
        else "<p><strong>Esta proposta expirou.</strong> Fale com a equipe para renova-la.</p>" if expired
        else f"<form method='post' action='{e(accept_url)}'><button type='submit'>Aceitar proposta</button></form>"
    )
    return page(
        "Proposta",
        f"<h1>Proposta - {e(agency)}</h1><div class='card'><h2>{e(plan_name)}</h2><ul>{feats}</ul>"
        f"<p><strong>Investimento:</strong> {e(price_text)}<br><strong>Valida ate:</strong> {e(valid_until)}</p></div>"
        f"<p><a href='{e(pdf_url)}'>Baixar PDF</a></p>{action}",
    )


BRIEFING_FIELDS = [
    ("nome_negocio", "Nome do negocio", "text"), ("segmento", "Segmento (ex.: barbearia)", "text"),
    ("cidade", "Cidade", "text"), ("endereco", "Endereco", "text"), ("horario", "Horario de funcionamento", "text"),
    ("telefone", "Telefone", "text"), ("whatsapp", "WhatsApp (com DDD)", "text"),
    ("instagram", "Instagram (opcional)", "text"), ("cor_principal", "Cor principal (ex.: #1f5fa8)", "text"),
    ("dominio_desejado", "Dominio desejado (opcional)", "text"),
]


def briefing_page(token: str, done: bool = False) -> str:
    if done:
        return page("Briefing", "<h1>Recebemos seu briefing!</h1><p>Em breve enviaremos a previa do seu site.</p>")
    fields = "".join(
        f"<label>{e(label)}<input name='{k}' type='{t}' maxlength='200'></label>" for k, label, t in BRIEFING_FIELDS
    )
    return page(
        "Briefing do site",
        "<h1>Vamos montar seu site</h1><p>Preencha o que souber. Seus dados sao usados apenas para criar o site.</p>"
        f"<form method='post' action='/public/briefing/{e(token)}'>{fields}"
        "<label>Descricao do negocio<textarea name='descricao' rows='4' maxlength='1000'></textarea></label>"
        "<label>Servicos (um por linha)<textarea name='servicos' rows='5' maxlength='1000'></textarea></label>"
        "<button type='submit'>Enviar</button></form>",
    )


def feedback_page(token: str, done: bool = False) -> str:
    if done:
        return page("Feedback", "<h1>Obrigado pelo retorno!</h1><p>Vamos ajustar e avisar voce.</p>")
    return page(
        "Feedback da previa",
        f"<h1>O que voce achou?</h1><form method='post' action='/public/preview/{e(token)}/feedback'>"
        "<label>Seu comentario<textarea name='comment' rows='5' maxlength='1000' required></textarea></label>"
        "<button type='submit'>Enviar feedback</button></form>",
    )


def nps_page(token: str, done: bool = False) -> str:
    if done:
        return page("NPS", "<h1>Obrigado!</h1><p>Sua opiniao nos ajuda a melhorar.</p>")
    opts = "".join(f"<option value='{i}'>{i}</option>" for i in range(10, -1, -1))
    return page(
        "Avaliacao",
        f"<h1>Como foi sua experiencia?</h1><form method='post' action='/public/nps/{e(token)}'>"
        f"<label>De 0 a 10, o quanto voce nos recomendaria?<select name='score'>{opts}</select></label>"
        "<label>Comentario (opcional)<textarea name='comment' rows='4' maxlength='1000'></textarea></label>"
        "<button type='submit'>Enviar</button></form>",
    )


def gone_page(msg: str = "Este link nao esta mais disponivel.") -> str:
    return page("Indisponivel", f"<h1>{e(msg)}</h1>")
