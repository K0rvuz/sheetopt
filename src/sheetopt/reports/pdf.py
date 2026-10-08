from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from html import escape
from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from sheetopt.models import AnalysisReport, Finding

INK = colors.HexColor("#18243A")
MUTED = colors.HexColor("#52647B")
GREEN = colors.HexColor("#147D65")
BORDER = colors.HexColor("#E0E7EF")
PALE = colors.HexColor("#F2F6FA")
SEVERITY_ORDER = ("critical", "high", "medium", "low", "info")
SEVERITY_LABEL = {
    "critical": "Crítica", "high": "Alta", "medium": "Média",
    "low": "Baixa", "info": "Informativa",
}


def _safe(text: object, limit: int = 5000) -> str:
    value = str(text)
    if len(value) > limit:
        value = value[:limit] + " [texto abreviado]"
    return escape(value).replace("\n", "<br/>")


def _make_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "SheetOptTitle", parent=base["Title"], fontName="Helvetica-Bold",
            fontSize=22, leading=28, textColor=INK, alignment=TA_LEFT,
            spaceAfter=6,
        ),
        "subtitle": ParagraphStyle(
            "SheetOptSubtitle", parent=base["Normal"], fontSize=10.5,
            leading=15, textColor=MUTED, spaceAfter=13,
        ),
        "section": ParagraphStyle(
            "SheetOptSection", parent=base["Heading2"], fontSize=13,
            leading=17, textColor=INK, spaceBefore=17, spaceAfter=8,
        ),
        "finding": ParagraphStyle(
            "SheetOptFinding", parent=base["Heading3"], fontSize=10.4,
            leading=14, textColor=INK, spaceAfter=5,
        ),
        "body": ParagraphStyle(
            "SheetOptBody", parent=base["Normal"], fontSize=9,
            leading=13, textColor=INK, spaceAfter=5, wordWrap="CJK",
        ),
        "small": ParagraphStyle(
            "SheetOptSmall", parent=base["Normal"], fontSize=8,
            leading=11, textColor=MUTED, spaceAfter=4, wordWrap="CJK",
        ),
        "cell": ParagraphStyle(
            "SheetOptCell", parent=base["Normal"], fontSize=8.5,
            leading=11, textColor=INK, wordWrap="CJK",
        ),
    }


def _table(rows: list[list[str]], widths: list[float], styles: dict[str, ParagraphStyle]) -> Table:
    cells = [[Paragraph(_safe(value), styles["cell"]) for value in row] for row in rows]
    table = Table(cells, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PALE),
        ("TEXTCOLOR", (0, 0), (-1, 0), INK),
        ("LINEBELOW", (0, 0), (-1, 0), 0.7, BORDER),
        ("LINEBELOW", (0, 1), (-1, -1), 0.35, BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return table


def _footer(canvas: Any, doc: SimpleDocTemplate) -> None:
    canvas.saveState()
    width, _ = A4
    canvas.setStrokeColor(BORDER)
    canvas.line(doc.leftMargin, 17 * mm, width - doc.rightMargin, 17 * mm)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(MUTED)
    canvas.drawString(doc.leftMargin, 12 * mm, "SheetOpt  |  Relatório de diagnóstico")
    canvas.drawRightString(width - doc.rightMargin, 12 * mm, f"Página {doc.page}")
    canvas.restoreState()


def _append_finding(
    story: list[Any], finding: Finding, index: int, styles: dict[str, ParagraphStyle]
) -> None:
    title = (
        f"{index:03d}  |  {finding.rule_id}  |  "
        f"{SEVERITY_LABEL.get(finding.severity, finding.severity)}  |  {finding.title}"
    )
    story.append(Paragraph(_safe(title), styles["finding"]))
    story.append(Paragraph(_safe(finding.message), styles["body"]))
    if finding.recommendations:
        story.append(Paragraph("<b>Recomendações para avaliação:</b>", styles["small"]))
        for item in finding.recommendations:
            story.append(Paragraph("- " + _safe(item, 1500), styles["small"]))
    if finding.locations:
        locations = ", ".join(finding.locations[:20])
        story.append(Paragraph("<b>Exemplos de células:</b> " + _safe(locations), styles["small"]))
    if finding.evidence:
        # Evidence may contain workbook-specific values; include only diagnostic
        # metadata, without expanding arbitrarily large nested content.
        for key, value in list(finding.evidence.items())[:8]:
            if isinstance(value, (str, int, float, bool)):
                story.append(Paragraph(
                    "<b>" + _safe(key, 120) + ":</b> " + _safe(value, 1200),
                    styles["small"],
                ))
    story.append(Spacer(1, 5 * mm))
    story.append(HRFlowable(width="100%", thickness=0.35, color=BORDER))
    story.append(Spacer(1, 3 * mm))


def build_report_pdf(
    report: AnalysisReport,
    *,
    status: str = "diagnosed",
    events: list[dict[str, Any]] | None = None,
) -> bytes:
    """Create a structured report from an existing diagnosis; never query Google."""
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=19 * mm, rightMargin=19 * mm,
        topMargin=20 * mm, bottomMargin=23 * mm,
        title="SheetOpt - Relatório de diagnóstico", author="SheetOpt",
    )
    styles = _make_styles()
    story: list[Any] = [
        Paragraph("SheetOpt", styles["title"]),
        Paragraph(
            "Relatório técnico de diagnóstico  |  "
            + _safe(datetime.now(UTC).strftime("%d/%m/%Y %H:%M UTC")),
            styles["subtitle"],
        ),
        Paragraph("<b>Planilha:</b> " + _safe(report.title, 350), styles["body"]),
        Paragraph(
            "<b>ID:</b> " + _safe(report.spreadsheet_id, 120), styles["small"]
        ),
        Spacer(1, 4 * mm),
        _table(
            [
                ["Abas", "Fórmulas", "Padrões", "Alertas"],
                [
                    f"{report.sheet_count:,}", f"{report.formula_count:,}",
                    f"{report.pattern_count:,}", str(len(report.findings)),
                ],
            ],
            [42 * mm, 44 * mm, 44 * mm, 42 * mm],
            styles,
        ),
        Spacer(1, 6 * mm),
        Paragraph(
            "<b>Estado:</b> " + _safe(status, 80) + ". "
            "Nenhuma otimização de fórmulas foi aplicada nesta versão. "
            "O número de alertas não representa quantidade de correções validadas. "
            "Ganho real de desempenho ainda não foi medido.",
            styles["body"],
        ),
    ]
    counts = Counter(f.severity for f in report.findings)
    story.append(Paragraph("Severidade dos alertas", styles["section"]))
    story.append(_table(
        [["Severidade", "Quantidade"]]
        + [
            [SEVERITY_LABEL[k], str(counts.get(k, 0))]
            for k in SEVERITY_ORDER if counts.get(k, 0)
        ]
        if report.findings else [["Severidade", "Quantidade"], ["Sem alertas", "0"]],
        [110 * mm, 62 * mm], styles,
    ))
    groups = Counter(f.rule_id for f in report.findings)
    story.append(Paragraph("Alertas por regra", styles["section"]))
    story.append(_table(
        [["Regra", "Ocorrências"]]
        + [[name, str(count)] for name, count in sorted(groups.items(), key=lambda item: (-item[1], item[0]))]
        if groups else [["Regra", "Ocorrências"], ["Nenhuma", "0"]],
        [110 * mm, 62 * mm], styles,
    ))
    if report.function_counts:
        story.append(Paragraph("Funções mais frequentes", styles["section"]))
        top_functions = sorted(report.function_counts.items(), key=lambda item: -item[1])[:15]
        story.append(_table(
            [["Função", "Ocorrências estimadas"]]
            + [[name, f"{count:,}"] for name, count in top_functions],
            [110 * mm, 62 * mm], styles,
        ))
    if events:
        story.append(Paragraph("Registro da execução", styles["section"]))
        rows = [["Etapa", "Situação", "Duração"]]
        names = {"read": "Leitura", "analyze": "Diagnóstico", "copy": "Cópia"}
        statuses = {
            "completed": "Concluída", "skipped": "Ignorada",
            "timeout": "Tempo esgotado",
        }
        for event in events[:15]:
            ms = event.get("duration_ms")
            duration = f"{ms / 1000:.2f} s" if isinstance(ms, (float, int)) else "-"
            rows.append([
                names.get(str(event.get("stage")), str(event.get("stage"))),
                statuses.get(str(event.get("status")), str(event.get("status"))),
                duration,
            ])
        story.append(_table(rows, [65 * mm, 62 * mm, 45 * mm], styles))
    story.append(Paragraph("Detalhamento de todos os alertas", styles["section"]))
    if not report.findings:
        story.append(Paragraph(
            "Nenhuma regra ultrapassou os limiares atuais de diagnóstico.",
            styles["body"],
        ))
    else:
        ordered = sorted(
            report.findings,
            key=lambda f: (
                SEVERITY_ORDER.index(f.severity),
                f.rule_id,
                f.message,
            ),
        )
        for index, finding in enumerate(ordered, start=1):
            # ReportLab will paginate long entries rather than clipping them.
            _append_finding(story, finding, index, styles)
    story.append(Paragraph(
        "Nota metodológica: as frequências são indicadores de diagnóstico. "
        "Os valores apresentados não comprovam ganho de performance. "
        "As recomendações devem passar por validação estrutural, testes de "
        "equivalência e medição antes de qualquer merge.",
        styles["small"],
    ))
    document.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buffer.getvalue()
