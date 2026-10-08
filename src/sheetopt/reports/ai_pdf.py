"""Review-only AI analysis export with deterministic JSON schema and PDF.

Exports contain only data the user saw in the approved context preview and the
structured model response. They do not access Google, Ollama, or saved tokens.
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from html import escape
from io import BytesIO
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

from sheetopt.ai.provider import AIAnalysis
from sheetopt.reports.pdf import BORDER, GREEN, INK, MUTED, _make_styles, _safe


class ExportDiagnostic(BaseModel):
    sheet_count: int = Field(ge=0, le=100000)
    formula_count: int = Field(ge=0, le=100000000)
    pattern_count: int = Field(ge=0, le=100000000)


class AIAnalysisExport(BaseModel):
    """No secrets, full diagnostic, values or complete original formulas."""
    schema_version: Literal[1] = 1
    generated_at: datetime
    provider: Literal["local", "external"]
    model: str = Field(min_length=1, max_length=150)
    destination: str = Field(default="", max_length=255)
    diagnostic: ExportDiagnostic
    context_packet: dict[str, Any]
    context_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    inference_elapsed_seconds: float | None = Field(default=None, ge=0, le=86400)
    analysis: AIAnalysis
    status: Literal["unverified_suggestions"] = "unverified_suggestions"
    writes_performed: Literal[False] = False
    performance_measured: Literal[False] = False
    merge_available: Literal[False] = False

    @model_validator(mode="after")
    def check_bounds_and_digest(self) -> AIAnalysisExport:
        raw = json.dumps(self.context_packet, ensure_ascii=False, sort_keys=True)
        if len(raw) > 16000:
            raise ValueError("Context packet exceeds the export size limit.")
        if hashlib.sha256(raw.encode("utf-8")).hexdigest() != self.context_sha256:
            raise ValueError("Context packet does not match the approved preview hash.")
        if len(self.model_dump_json()) > 60000:
            raise ValueError("AI report exceeds the export size limit.")
        return self


def build_ai_analysis_pdf(export_data: AIAnalysisExport) -> bytes:
    """Complete, paginated, searchable PDF with sources and context appendix."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=19 * mm,
        rightMargin=19 * mm,
        topMargin=20 * mm,
        bottomMargin=23 * mm,
        title="SheetOpt - Análise contextual de IA",
        author="SheetOpt",
    )
    styles = _make_styles()
    styles["mono"] = ParagraphStyle(
        "SheetOptAIContextMono",
        parent=styles["small"],
        fontName="Courier",
        fontSize=6.8,
        leading=9.5,
        textColor=MUTED,
        wordWrap="CJK",
        leftIndent=5,
        spaceAfter=1.5,
    )
    styles["risk"] = ParagraphStyle(
        "SheetOptAIRisk",
        parent=styles["body"],
        textColor=colors.HexColor("#975300"),
        spaceAfter=9,
    )
    story: list[Any] = []

    def block(value: str, *, style: str = "body", limit: int = 15000) -> None:
        story.append(Paragraph(_safe(value, limit), styles[style]))

    def header(value: str) -> None:
        story.append(Paragraph(_safe(value, 500), styles["section"]))

    def foot(canvas: Any, document: SimpleDocTemplate) -> None:
        canvas.saveState()
        width, _ = A4
        canvas.setStrokeColor(BORDER)
        canvas.line(document.leftMargin, 17 * mm, width - document.rightMargin, 17 * mm)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(MUTED)
        canvas.drawString(document.leftMargin, 12 * mm, "SheetOpt | Análise contextual de IA")
        canvas.drawRightString(width - document.rightMargin, 12 * mm, f"Página {document.page}")
        canvas.restoreState()

    story.append(Paragraph("SheetOpt", styles["title"]))
    block("RELATÓRIO DE ANÁLISE POR IA | NÃO VALIDADO", style="subtitle")
    date = export_data.generated_at.astimezone(UTC).strftime("%d/%m/%Y %H:%M UTC")
    block(f"Gerado em: {date}")
    block(f"Modelo: {export_data.model} | Provedor: {export_data.provider}")
    block(f"Destino do modelo: {export_data.destination or 'Não informado'}")
    if export_data.inference_elapsed_seconds is not None:
        block(
            "Espera da requisição (não é benchmark): "
            f"{export_data.inference_elapsed_seconds:.1f} segundos",
            style="small",
        )
    d = export_data.diagnostic
    block(
        f"Contexto do diagnóstico: {d.sheet_count:,} abas; "
        f"{d.formula_count:,} fórmulas; {d.pattern_count:,} padrões."
    )
    story.append(Spacer(1, 3 * mm))
    block(
        "IMPORTANTE: hipóteses geradas por modelo de linguagem, não alterações "
        "executadas. Equivalência entre fórmulas, ganho de desempenho e segurança "
        "da transformação NÃO foram comprovados. Nenhuma célula foi modificada.",
        style="risk",
    )
    header("Resumo da análise")
    block(export_data.analysis.summary)

    header(f"Propostas recebidas ({len(export_data.analysis.proposals)})")
    if not export_data.analysis.proposals:
        block("O modelo não apresentou propostas.", style="small")
    for index, proposal in enumerate(export_data.analysis.proposals, start=1):
        story.append(KeepTogether([
            Paragraph(_safe(f"{index}. {proposal.title}", 200), styles["finding"]),
            Paragraph(
                _safe(f"Impacto hipotético: {proposal.impact} | Risco: {proposal.risk}"),
                styles["small"],
            ),
        ]))
        if proposal.target_sheets:
            block("Abas citadas: " + ", ".join(proposal.target_sheets), style="small")
        block(proposal.rationale)
        if proposal.validation_steps:
            block("Validações obrigatórias antes de qualquer alteração:", style="small")
            for step in proposal.validation_steps:
                block("• " + step, style="small", limit=500)
        if proposal.source_ids:
            block("Fontes citadas: " + ", ".join(proposal.source_ids), style="small")
        story.append(Spacer(1, 2 * mm))
        story.append(HRFlowable(width="100%", thickness=0.35, color=BORDER))
        story.append(Spacer(1, 3 * mm))

    header("Informações adicionais necessárias")
    if export_data.analysis.missing_context:
        for item in export_data.analysis.missing_context:
            block("• " + item, style="small", limit=600)
    else:
        block("O modelo não solicitou contexto adicional.", style="small")

    header("Fontes de documentação incluídas no contexto")
    sources = export_data.context_packet.get("knowledge_sources", [])
    if isinstance(sources, list):
        for source in sources[:8]:
            if not isinstance(source, dict):
                continue
            block(
                f"{source.get('source_id', '?')}: {source.get('title', '')}",
                style="finding",
                limit=350,
            )
            block(str(source.get("guidance", "")), style="small", limit=1600)
            block("URL: " + str(source.get("source_url", "")), style="small", limit=550)
    if not sources:
        block("Nenhuma fonte adicional fornecida ao modelo.", style="small")

    header("Apêndice: pacote exato enviado à IA")
    block(
        "Este pacote foi preparado pelo SheetOpt. Os identificadores podem "
        "ter sido anonimizados antes da inferência. Inclui a documentação recuperada.",
        style="small",
    )
    block("SHA-256: " + export_data.context_sha256, style="small")
    # Long JSON is split into paragraphs so ReportLab can paginate; no clipped
    # preformatted block and no unescaped markup from any model response.
    packet_json = json.dumps(
        export_data.context_packet, ensure_ascii=False, indent=2, sort_keys=True
    )
    for line in packet_json.splitlines():
        story.append(Paragraph(
            escape(line).replace(" ", "&nbsp;") or "&nbsp;",
            styles["mono"],
        ))

    story.append(Spacer(1, 3 * mm))
    block(
        "Status: unverified_suggestions. Nenhuma escrita, benchmark de "
        "performance ou merge foi executado.",
        style="small",
    )
    doc.build(story, onFirstPage=foot, onLaterPages=foot)
    return buffer.getvalue()
