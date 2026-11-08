"""PDF da proposta comercial (ReportLab, sem dependencias de sistema)."""

import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from xml.sax.saxutils import escape


def render_proposal_pdf(
    *, agency: str, client_name: str | None, plan_name: str, plan_description: str | None,
    features: list[str], price_text: str, valid_until: str, accept_url: str, notes: str | None,
) -> bytes:
    base = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=base["Title"], fontSize=22, textColor=colors.HexColor("#1f5fa8"))
    body = ParagraphStyle("b", parent=base["BodyText"], fontSize=11, leading=15)
    small = ParagraphStyle("s", parent=body, fontSize=9, textColor=colors.HexColor("#555555"))
    p = lambda t, s=body: Paragraph(escape(t or ""), s)  # noqa: E731 - todo texto de terceiros e escapado

    story = [
        p("Proposta comercial", h1),
        p(f"{agency}", small), Spacer(1, 12),
        p(f"Cliente: {client_name or 'a confirmar'}"),
        p(f"Plano: {plan_name}"), Spacer(1, 6),
    ]
    if plan_description:
        story += [p(plan_description), Spacer(1, 6)]
    if features:
        story += [p("O que esta incluso:")] + [p(f"- {f}") for f in features] + [Spacer(1, 8)]
    table = Table([["Investimento", price_text], ["Validade da proposta", valid_until]], colWidths=[6 * cm, 9 * cm])
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef3fa")),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"), ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("PADDING", (0, 0), (-1, -1), 8),
    ]))
    story += [table, Spacer(1, 12)]
    if notes:
        story += [p("Observacoes:"), p(notes), Spacer(1, 8)]
    story += [
        p("Para aceitar esta proposta, acesse o link abaixo. O aceite fica registrado com data e hora."),
        p(accept_url, small), Spacer(1, 14),
        p("Valores e prazos so valem conforme esta proposta. Qualquer alteracao deve ser confirmada por um atendente.", small),
    ]
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm,
                      title=f"Proposta - {plan_name}").build(story)
    return buf.getvalue()
