"use strict";

// The report lives in browser memory after the analysis completes. No second
// Google Sheets read is required for filtering or downloading the PDF/JSON.
(() => {
  const severityNames = {
    critical: "Crítica", high: "Alta", medium: "Média",
    low: "Baixa", info: "Informativa"
  };
  const severityOrder = ["critical", "high", "medium", "low", "info"];
  const ruleNames = {
    "PERF-001": "Fórmulas estruturalmente repetidas",
    "PERF-002": "Agregações SUMIFS repetidas",
    "PERF-003": "Referências a colunas inteiras",
    "PERF-004": "Importações IMPORTRANGE duplicadas"
  };
  const stages = { read: "Leitura das abas e fórmulas", analyze: "Análise das regras", context: "Mapeamento de contexto", copy: "Cópia de trabalho" };
  const stageStates = { completed: "Concluído", skipped: "Ignorado", timeout: "Tempo esgotado" };
  const $node = (tag, value, className) => {
    const element = document.createElement(tag);
    if (value !== undefined && value !== null) element.textContent = String(value);
    if (className) element.className = className;
    return element;
  };
  const quantity = (value) => Number(value || 0).toLocaleString("pt-BR");
  const validCloneUrl = (url) => {
    try {
      const parsed = new URL(url);
      return parsed.protocol === "https:" && parsed.hostname === "docs.google.com" &&
        parsed.pathname.startsWith("/spreadsheets/d/") ? parsed.href : null;
    } catch (_) {
      return null;
    }
  };
  function downloadBlob(name, blob) {
    const url = URL.createObjectURL(blob);
    const link = $node("a");
    link.href = url;
    link.download = name;
    document.body.append(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1500);
  }
  function addMetric(parent, label, value) {
    const el = $node("div", null, "report-metric");
    el.append($node("span", label), $node("strong", quantity(value)));
    parent.append(el);
  }
  function addButton(parent, label, onClick, className = "secondary") {
    const button = $node("button", label, className);
    button.type = "button";
    button.addEventListener("click", onClick);
    parent.append(button);
    return button;
  }
  function itemCard(finding) {
    const item = $node("article", null, "finding");
    const heading = $node("div", null, "finding-header");
    heading.append(
      $node("strong", finding.title),
      $node("span", severityNames[finding.severity] || finding.severity, "severity " + finding.severity)
    );
    item.append(heading, $node("p", finding.message));
    if (Array.isArray(finding.recommendations) && finding.recommendations.length) {
      const recommendations = $node("details", null, "finding-extra");
      recommendations.append($node("summary", "Recomendações para avaliação"));
      const list = $node("ul");
      for (const item of finding.recommendations) list.append($node("li", item));
      recommendations.append(list);
      item.append(recommendations);
    }
    if (Array.isArray(finding.locations) && finding.locations.length) {
      const locations = $node("p", null, "finding-locations");
      locations.append($node("strong", "Exemplos: "));
      locations.append(document.createTextNode(finding.locations.slice(0, 6).join(", ")));
      item.append(locations);
    }
    return item;
  }
  function filteredGroups(report, severity, search) {
    const groups = new Map();
    for (const finding of report.findings) {
      if (severity && finding.severity !== severity) continue;
      const haystack = [
        finding.rule_id, finding.title, finding.message,
        ...(finding.locations || [])
      ].join(" ").toLocaleLowerCase();
      if (search && !haystack.includes(search)) continue;
      if (!groups.has(finding.rule_id)) groups.set(finding.rule_id, []);
      groups.get(finding.rule_id).push(finding);
    }
    for (const value of groups.values()) {
      value.sort((a, b) =>
        severityOrder.indexOf(a.severity) - severityOrder.indexOf(b.severity)
      );
    }
    return [...groups.entries()].sort((a, b) => b[1].length - a[1].length);
  }
  function renderGroups(target, report, severity, search) {
    target.replaceChildren();
    const groups = filteredGroups(report, severity, search);
    const total = groups.reduce((sum, group) => sum + group[1].length, 0);
    target.append($node("p",
      quantity(total) + " alerta(s) encontrados em " + groups.length + " grupo(s).", "muted"
    ));
    if (!groups.length) {
      target.append($node("p", "Nenhum alerta corresponde aos filtros escolhidos.", "muted"));
      return;
    }
    for (const [rule, findings] of groups) {
      const section = $node("details", null, "report-group");
      const summary = $node("summary");
      summary.append(
        $node("strong", rule + " · " + (ruleNames[rule] || "Regra de diagnóstico")),
        $node("span", quantity(findings.length) + " alertas", "pill")
      );
      section.append(summary);
      // Insert cards only when this rule is expanded; 258+ cards must not be
      // mounted by default on dashboards with hundreds of findings.
      section.addEventListener("toggle", () => {
        if (!section.open || section.dataset.loaded === "1") return;
        section.dataset.loaded = "1";
        const list = $node("div", null, "report-group-body");
        const first = findings.slice(0, 15);
        for (const finding of first) list.append(itemCard(finding));
        if (findings.length > first.length) {
          addButton(list, "Mostrar os " + quantity(findings.length - first.length) + " alertas restantes", (event) => {
            for (const finding of findings.slice(first.length)) list.append(itemCard(finding));
            event.target.remove();
          });
        }
        section.append(list);
      });
      target.append(section);
    }
  }
  function buildTimeline(container, events) {
    const details = $node("details", null, "report-timeline");
    details.append($node("summary", "Registro da execução"));
    const content = $node("ol");
    if (!events.length) {
      content.append($node("li", "Diagnóstico somente leitura concluído. Sem duração por etapa disponível."));
    }
    for (const item of events) {
      const stage = stages[item.stage] || item.stage;
      const state = stageStates[item.status] || item.status;
      const duration = typeof item.duration_ms === "number"
        ? " · " + (item.duration_ms / 1000).toLocaleString("pt-BR", {maximumFractionDigits: 2}) + " s"
        : "";
      content.append($node("li", stage + " — " + state + duration));
    }
    details.append(content);
    container.append(details);
  }
  function renderAiAssistant(root, result, token) {
    if (!result.context) return;

    const panel = $node("details", null, "report-details ai-assistant");
    panel.append($node("summary", "IA contextual · Investigar e gerar propostas"));

    const intro = $node("div", null, "ai-intro");
    intro.append($node("p",
      "Analise a estrutura da planilha em três etapas: escolha o escopo, " +
      "confira os dados e autorize a consulta. A IA não modifica fórmulas.",
      "muted"
    ));
    const settingsLink = $node("a", "Configurar provedor de IA ↗");
    settingsLink.href = "#ai";
    intro.append(settingsLink);
    panel.append(intro);

    const makeStep = (number, title, description) => {
      const step = $node("section", null, "ai-step");
      const heading = $node("div", null, "ai-step-heading");
      const numberEl = $node("span", number, "ai-step-number");
      const titleBlock = $node("div");
      titleBlock.append($node("h4", title));
      titleBlock.append($node("p", description, "muted"));
      heading.append(numberEl, titleBlock);
      step.append(heading);
      panel.append(step);
      return step;
    };

    const scopeStep = makeStep("1", "Escolher a investigação",
      "Use uma aba específica ou examine o documento inteiro.");
    const scopeGrid = $node("div", null, "ai-scope-grid");

    const focusField = $node("div", null, "ai-field");
    const focusLabel = $node("label", "Aba analisada");
    const focus = $node("select");
    focus.setAttribute("aria-label", "Aba para análise por IA");
    const all = $node("option", "Visão geral do documento");
    all.value = "";
    focus.append(all);
    for (const sh of (result.context.sheets || []).slice(0, 80)) {
      const option = $node("option", sh.name);
      option.value = sh.name;
      focus.append(option);
    }
    focusField.append(focusLabel, focus);

    const typeField = $node("div", null, "ai-field");
    const typeLabel = $node("label", "Tipo de investigação");
    const investigation = $node("select");
    investigation.setAttribute("aria-label", "Tipo de investigação contextual");
    for (const [value, label] of [
      ["overview", "Panorama geral"],
      ["upstream", "Fontes consultadas pela aba"],
      ["downstream", "Abas dependentes"],
      ["hotspots", "Intervalos críticos"]
    ]) {
      const option = $node("option", label);
      option.value = value;
      investigation.append(option);
    }
    typeField.append(typeLabel, investigation);
    scopeGrid.append(focusField, typeField);
    scopeStep.append(scopeGrid);

    const privacyLabel = $node("label", null, "ai-checkbox ai-privacy");
    const includeNames = $node("input");
    includeNames.type = "checkbox";
    const privacyText = $node("span");
    privacyText.append($node("strong", "Incluir nomes de abas e cabeçalhos"));
    privacyText.append($node("small",
      "Desmarcado por padrão. IDs, fórmulas completas e valores não são enviados."
    ));
    privacyLabel.append(includeNames, privacyText);
    scopeStep.append(privacyLabel);

    const previewStep = makeStep("2", "Revisar o contexto",
      "A prévia é local e mostra exatamente o pacote antes de qualquer envio à IA.");
    const actions = $node("div", null, "ai-action-row");
    const probeButton = addButton(actions, "Investigar sem IA", () => {}, "secondary");
    const previewButton = addButton(actions, "Visualizar pacote para IA", () => {}, "secondary");
    previewStep.append(actions);

    const previewInfo = $node("div", null, "ai-preview");
    previewInfo.append($node("p",
      "Escolha o escopo e visualize o pacote. Nenhuma consulta ao modelo foi feita.",
      "muted"
    ));
    previewStep.append(previewInfo);
    const evidenceBox = $node("div", null, "ai-evidence");
    evidenceBox.append($node("h4", "Amostras de fórmulas (opcional)"));
    evidenceBox.append($node("p",
      "O SheetOpt pode reler até seis células dos alertas da aba escolhida. " +
      "Textos, nomes de abas e constantes são ocultados antes da prévia.",
      "muted"));
    const sampleButton = addButton(evidenceBox,
      "Buscar amostras no Google (somente leitura)", () => {}, "secondary");
    const sampleResult = $node("div", null, "ai-evidence-samples");
    evidenceBox.append(sampleResult);
    const sampleLabel = $node("label", null, "ai-checkbox ai-sample-consent");
    const includeSamples = $node("input");
    includeSamples.type = "checkbox";
    includeSamples.disabled = true;
    const sampleText = $node("span");
    sampleText.append($node("strong",
      "Incluir amostras sanitizadas na consulta ao modelo"));
    sampleText.append($node("small",
      "Desmarcado por padrão. Confira os exemplos antes de autorizar o envio."));
    sampleLabel.append(includeSamples, sampleText);
    evidenceBox.append(sampleLabel);
    previewStep.append(evidenceBox);

    const consentStep = makeStep("3", "Autorizar e gerar",
      "O modelo só será consultado após revisar a prévia e marcar a autorização.");
    const approve = $node("label", null, "ai-checkbox ai-consent");
    const consent = $node("input");
    consent.type = "checkbox";
    consent.disabled = true;
    const consentText = $node("span");
    consentText.append($node("strong",
      "Li a prévia e autorizo o envio deste pacote ao provedor configurado."
    ));
    approve.append(consent, consentText);
    consentStep.append(approve);

    const runButton = addButton(consentStep, "Gerar propostas com IA", () => {});
    runButton.classList.add("ai-run");
    runButton.disabled = true;

    const progress = $node("div", null, "ai-progress");
    progress.hidden = true;
    progress.setAttribute("role", "status");
    progress.setAttribute("aria-live", "polite");
    const progressHeader = $node("div", null, "ai-progress-header");
    const spinner = $node("span", null, "ai-spinner");
    spinner.setAttribute("aria-hidden", "true");
    const progressInfo = $node("div", null, "ai-progress-info");
    const progressTitle = $node("strong", "Aguardando...");
    const progressDescription = $node("p", "", "muted");
    progressInfo.append(progressTitle, progressDescription);
    progressHeader.append(spinner, progressInfo);
    const progressBar = $node("div", null, "ai-progress-track");
    progressBar.setAttribute("role", "progressbar");
    progressBar.setAttribute("aria-label", "Processamento da IA em andamento");
    progressBar.append($node("span", null, "ai-progress-fill"));
    const progressFooter = $node("div", null, "ai-progress-footer");
    const elapsedText = $node("span", "Tempo decorrido: 00:00");
    elapsedText.setAttribute("aria-hidden", "true");
    progressFooter.append(elapsedText, $node("span",
      "Indicador de atividade, não de porcentagem concluída."
    ));
    progress.append(progressHeader, progressBar, progressFooter);
    consentStep.append(progress);

    const resultArea = $node("div", null, "ai-suggestions");
    resultArea.setAttribute("aria-live", "polite");
    consentStep.append(resultArea);

    let formulaSamples = [];
    let previewHash = null;
    let approvedPacket = null;
    let previewDestination = "";
    let previewReady = false;
    let busy = false;
    let timer = null;
    let started = 0;

    const packetRequest = () => ({
      report: result.report,
      context: result.context || null,
      opportunities: result.aggregation_opportunities || [],
      focus_sheet: focus.value || null,
      investigation: investigation.value,
      include_identifiers: includeNames.checked,
      formula_samples: includeSamples.checked ? formulaSamples : []
    });

    const duration = (seconds) => {
      const minutes = String(Math.floor(seconds / 60)).padStart(2, "0");
      const remainder = String(seconds % 60).padStart(2, "0");
      return minutes + ":" + remainder;
    };
    const updateElapsed = () => {
      elapsedText.textContent = "Tempo decorrido: " +
        duration(Math.floor((Date.now() - started) / 1000));
    };
    const setBusy = (active, title = "", description = "") => {
      busy = active;
      focus.disabled = active;
      investigation.disabled = active;
      includeNames.disabled = active;
      probeButton.disabled = active;
      previewButton.disabled = active;
      sampleButton.disabled = active;
      includeSamples.disabled = active || !formulaSamples.length;
      consent.disabled = active || !previewReady;
      runButton.disabled = active || !previewReady || !consent.checked || !previewHash;
      if (timer !== null) {
        window.clearInterval(timer);
        timer = null;
      }
      if (active) {
        started = Date.now();
        progressTitle.textContent = title;
        progressDescription.textContent = description;
        progress.hidden = false;
        progress.classList.add("is-running");
        progress.classList.remove("is-complete");
        updateElapsed();
        timer = window.setInterval(updateElapsed, 1000);
      } else {
        progress.classList.remove("is-running");
      }
    };
    const showCompletion = (message) => {
      progressTitle.textContent = message;
      progressDescription.textContent = "A resposta chegou ao SheetOpt.";
      progress.classList.add("is-complete");
      progress.classList.remove("is-running");
    };
    const reset = () => {
      previewHash = null;
      approvedPacket = null;
      previewDestination = "";
      previewReady = false;
      consent.checked = false;
      consent.disabled = true;
      runButton.disabled = true;
      progress.hidden = true;
      resultArea.replaceChildren();
      previewInfo.replaceChildren($node("p",
        "O escopo mudou. Gere uma nova prévia antes de autorizar o envio.",
        "muted"
      ));
    };
    const clearSampleEvidence = () => {
      formulaSamples = [];
      includeSamples.checked = false;
      includeSamples.disabled = true;
      sampleResult.replaceChildren();
      reset();
    };
    focus.addEventListener("change", clearSampleEvidence);
    investigation.addEventListener("change", reset);
    includeNames.addEventListener("change", reset);
    includeSamples.addEventListener("change", reset);
    consent.addEventListener("change", () => {
      runButton.disabled = busy || !previewReady || !consent.checked || !previewHash;
    });

    const post = async (path, data) => {
      const response = await fetch(path, {
        method: "POST",
        headers: {
          "Authorization": "Bearer " + token,
          "Content-Type": "application/json"
        },
        body: JSON.stringify(data),
        cache: "no-store"
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(typeof body.detail === "string"
          ? body.detail : "Não foi possível concluir a operação (HTTP " +
            response.status + ").");
      }
      return body;
    };

    const renderPayload = (data, prefix) => {
      previewInfo.replaceChildren();
      previewInfo.append($node("p", prefix, "muted"));
      const metadata = $node("div", null, "ai-preview-meta");
      if ("destination" in data) {
        metadata.append(
          $node("span", "Destino: " + (data.destination || "não configurado")),
          $node("span", "Modelo: " + (data.model || "não configurado"))
        );
      }
      metadata.append($node("span",
        "Tamanho: " + quantity(data.packet_chars ||
          JSON.stringify(data.packet || {}).length) + " caracteres"
      ));
      previewInfo.append(metadata);
      const details = $node("details", null, "ai-payload-details");
      details.append($node("summary", "Inspecionar JSON exato do contexto"));
      details.append($node("pre", JSON.stringify(data.packet, null, 2), "ai-json"));
      previewInfo.append(details);
      const references = data.packet?.knowledge_sources || [];
      if (references.length) {
        const citations = $node("details", null, "ai-payload-details");
        citations.append($node("summary",
          "Documentação oficial recuperada · " + references.length));
        for (const source of references) {
          const item = $node("div", null, "ai-source");
          const link = $node("a", source.source_id + " — " + source.title);
          link.href = source.source_url;
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          item.append(link, $node("p", source.guidance, "muted"));
          citations.append(item);
        }
        previewInfo.append(citations);
      }
    };

    previewButton.addEventListener("click", async () => {
      if (busy) return;
      reset();
      setBusy(true, "Preparando prévia...", "Nenhuma chamada ao modelo é feita nesta etapa.");
      try {
        const data = await post("/v1/ai/preview", packetRequest());
        previewHash = data.preview_hash;
        approvedPacket = data.packet;
        previewDestination = data.destination || "";
        previewReady = data.ready === true;
        renderPayload(data, data.ready
          ? "Prévia pronta. Confira o pacote e o destino antes de autorizar."
          : "O provedor não está configurado. Configure a IA e gere uma nova prévia.");
        consent.disabled = !previewReady;
        showCompletion("Prévia concluída");
      } catch (error) {
        previewInfo.replaceChildren($node("p", error.message, "warning"));
        progress.hidden = true;
      } finally {
        setBusy(false);
      }
    });

    probeButton.addEventListener("click", async () => {
      if (busy) return;
      reset();
      setBusy(true, "Investigando contexto...", "Consulta somente ao diagnóstico local.");
      try {
        const data = await post("/v1/ai/investigate", packetRequest());
        renderPayload(data, "Investigação local concluída. Nenhum dado foi enviado à IA.");
        showCompletion("Investigação concluída");
      } catch (error) {
        previewInfo.replaceChildren($node("p", error.message, "warning"));
        progress.hidden = true;
      } finally {
        setBusy(false);
      }
    });

    sampleButton.addEventListener("click", async () => {
      if (busy) return;
      if (!focus.value) {
        sampleResult.replaceChildren($node("p",
          "Selecione uma aba antes de buscar fórmulas.", "warning"));
        return;
      }
      clearSampleEvidence();
      setBusy(true, "Buscando exemplos...", "Lendo somente células indicadas pelos alertas.");
      try {
        const data = await post("/v1/ai/formula-samples", {
          report: result.report,
          context: result.context,
          focus_sheet: focus.value,
          read_consent: true
        });
        formulaSamples = (data.examples || []).slice(0, 6).map(item => ({
          sheet: focus.value, a1: item.a1, formula_template: item.formula_template
        }));
        sampleResult.replaceChildren($node("p",
          formulaSamples.length
            ? "Exemplos sanitizados. Nada foi enviado à IA."
            : "Não foram encontradas células elegíveis nos alertas desta aba.",
          "muted"));
        for (const item of formulaSamples) {
          const row = $node("div", null, "ai-sample-row");
          row.append($node("strong", item.a1),
            $node("code", item.formula_template));
          sampleResult.append(row);
        }
        includeSamples.disabled = !formulaSamples.length;
        showCompletion("Amostras disponíveis");
      } catch (error) {
        sampleResult.replaceChildren($node("p", error.message, "warning"));
        progress.hidden = true;
      } finally {
        setBusy(false);
      }
    });

    runButton.addEventListener("click", async () => {
      if (busy || !consent.checked || !previewHash || !previewReady) return;
      const approvedHash = previewHash;
      const sentPacket = approvedPacket;
      const destination = previewDestination;
      resultArea.replaceChildren();
      setBusy(true, "Consultando o modelo...",
        "O Ollama está preparando uma resposta. Modelos locais podem " +
        "levar vários minutos. Mantenha esta página aberta.");
      runButton.textContent = "Processando análise...";
      try {
        const data = await post("/v1/ai/suggest", {
          ...packetRequest(),
          consent: true,
          preview_hash: approvedHash
        });
        resultArea.replaceChildren();
        const resultHeading = $node("h4", "Propostas recebidas");
        resultArea.append(resultHeading);
        resultArea.append($node("p", data.result.summary, "muted"));
        for (const proposal of data.result.proposals || []) {
          const section = $node("details", null, "report-group");
          section.append($node("summary", proposal.title));
          const inner = $node("div", null, "report-group-body");
          inner.append($node("p", proposal.rationale, "muted"));
          if (proposal.evidence_status) {
            const classification = proposal.evidence_status === "needs_evidence"
              ? "Evidência insuficiente — não executar"
              : "Investigação fundamentada — ainda requer testes";
            inner.append($node("p", "Validador: " + classification,
              proposal.evidence_status === "needs_evidence" ? "warning" : "muted"));
          }
          if (proposal.evidence_reasons?.length) {
            const reasons = $node("ul");
            for (const reason of proposal.evidence_reasons) {
              reasons.append($node("li", reason));
            }
            inner.append($node("strong", "Limitações detectadas"));
            inner.append(reasons);
          }
          if (proposal.evidence_rules?.length) {
            inner.append($node("p", "Regras documentais: " +
              proposal.evidence_rules.join(", "), "muted"));
          }
          inner.append($node("p",
            "Impacto estimado: " + proposal.impact +
            " · Risco: " + proposal.risk +
            " · Abas: " + (proposal.target_sheets || []).join(", "), "muted"
          ));
          const steps = $node("ul");
          for (const step of proposal.validation_steps || []) {
            steps.append($node("li", step));
          }
          inner.append($node("strong", "Verificações necessárias"));
          inner.append(steps);
          section.append(inner);
          resultArea.append(section);
        }
        if (data.result.missing_context?.length) {
          const missing = $node("details", null, "report-group");
          missing.append($node("summary", "Informações adicionais necessárias"));
          const list = $node("ul");
          for (const item of data.result.missing_context) list.append($node("li", item));
          missing.append(list);
          resultArea.append(missing);
        }
        resultArea.append($node("p",
          "Sugestões não verificadas. Desempenho não medido; merge indisponível.",
          "warning"
        ));
        // A complete review-only export is constructed from the exact approved
        // context packet and the structured response, not from HTML summaries.
        const record = {
          schema_version: 1,
          generated_at: new Date().toISOString(),
          provider: data.provider,
          model: data.model,
          destination,
          diagnostic: {
            sheet_count: result.report.sheet_count,
            formula_count: result.report.formula_count,
            pattern_count: result.report.pattern_count
          },
          context_packet: sentPacket,
          context_sha256: approvedHash,
          inference_elapsed_seconds: Math.round((Date.now() - started) / 100) / 10,
          analysis: data.result,
          status: "unverified_suggestions",
          writes_performed: false,
          performance_measured: false,
          merge_available: false
        };
        const exportPanel = $node("section", null, "ai-export");
        exportPanel.append($node("h4", "Baixar análise completa"));
        exportPanel.append($node("p",
          "Inclui todas as propostas, riscos, verificações, dúvidas, fontes e " +
          "o contexto enviado ao modelo. Nenhuma otimização foi validada.",
          "muted"
        ));
        const buttons = $node("div", null, "ai-action-row");
        addButton(buttons, "Exportar JSON completo", () => {
          const blob = new Blob([JSON.stringify(record, null, 2)], {
            type: "application/json;charset=utf-8"
          });
          downloadBlob("sheetopt-analise-ia.json", blob);
        }, "secondary");
        const pdfButton = addButton(buttons, "Exportar PDF completo", async () => {
          pdfButton.disabled = true;
          pdfButton.textContent = "Preparando PDF...";
          try {
            const response = await fetch("/v1/reports/ai/pdf", {
              method: "POST",
              headers: {
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json"
              },
              body: JSON.stringify(record),
              cache: "no-store"
            });
            if (!response.ok) {
              const errorData = await response.json().catch(() => ({}));
              throw new Error(typeof errorData.detail === "string"
                ? errorData.detail
                : "Falha ao gerar o PDF (HTTP " + response.status + ").");
            }
            const blob = await response.blob();
            if (blob.type !== "application/pdf") {
              throw new Error("O servidor não retornou um PDF válido.");
            }
            downloadBlob("sheetopt-analise-ia.pdf", blob);
          } catch (error) {
            exportPanel.append($node("p",
              "Erro na exportação: " + error.message, "warning"
            ));
          } finally {
            pdfButton.disabled = false;
            pdfButton.textContent = "Exportar PDF completo";
          }
        }, "secondary");
        exportPanel.append(buttons);
        resultArea.append(exportPanel);
        showCompletion("Análise concluída");
      } catch (error) {
        resultArea.replaceChildren($node("p",
          "A análise não foi concluída: " + error.message +
          " Você pode gerar uma nova prévia para tentar novamente.",
          "warning"
        ));
        progressTitle.textContent = "Falha na consulta";
        progressDescription.textContent = "O modelo não retornou propostas utilizáveis.";
        progress.classList.remove("is-running");
        progress.classList.add("is-complete");
      } finally {
        previewHash = null;
        previewReady = false;
        consent.checked = false;
        runButton.textContent = "Gerar propostas com IA";
        setBusy(false);
      }
    });

    root.append(panel);
  }

  function renderEvidenceHistory(root, token) {
    const panel = $node("details", null, "report-details");
    panel.append($node("summary", "Histórico local de testes e evidências"));
    panel.append($node("p",
      "Mostra apenas testes efetuados pelo validador do SheetOpt. " +
      "A versão atual NÃO mede tempo de recálculo nem comprova ganhos globais.",
      "muted"
    ));
    const target = $node("div");
    addButton(panel, "Consultar histórico local", async (event) => {
      const button = event.currentTarget;
      button.disabled = true;
      try {
        const response = await fetch("/v1/evidence/trials?limit=30", {
          headers: {"Authorization": "Bearer " + token}, cache: "no-store"
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error("Histórico indisponível.");
        target.replaceChildren(
          $node("p",
            quantity(data.summary.trial_count) + " teste(s) registrados; " +
            "ganhos de desempenho medidos: 0.", "muted")
        );
        for (const trial of data.records || []) {
          target.append($node("p",
            trial.rule_id + " · " + trial.status + " · " +
            new Date(trial.timestamp * 1000).toLocaleString("pt-BR"),
            "muted"
          ));
        }
      } catch (error) {
        target.replaceChildren($node("p", error.message, "warning"));
      } finally {
        button.disabled = false;
      }
    });
    panel.append(target);
    root.append(panel);
  }

  function renderWorkbookContext(root, result) {
    const context = result.context;
    if (!context) return;
    const panel = $node("details", null, "report-details");
    panel.append($node("summary",
      "Contexto estrutural do documento · " + quantity(context.sheet_count) + " abas"
    ));
    const complete = context.coverage === "formula_snapshot";
    panel.append($node("p",
      complete
        ? "Inventário gerado a partir de todas as fórmulas lidas. As conexões mostram " +
          "apenas referências explícitas entre abas, não o grafo completo de células."
        : "Contexto parcial reconstruído do JSON de diagnóstico. " +
          "Não contém a lista completa de abas nem arestas de dependência verificáveis.",
      "muted"
    ));
    const total = $node("p", complete
      ? quantity(context.edge_count_total) + " conexões entre abas; " +
        quantity(context.dynamic_formula_count) + " fórmulas com funções dinâmicas."
      : "Para construir as dependências entre abas é necessário reler a planilha com sua conta Google.",
      "muted"
    );
    panel.append(total);
    const edges = (context.edges || []).slice(0, 15);
    if (edges.length) {
      const sub = $node("details", null, "report-group");
      sub.append($node("summary", "Dependências explícitas entre abas"));
      const body = $node("div", null, "report-group-body");
      for (const edge of edges) {
        body.append($node("p",
          edge.from_sheet + " → " + edge.depends_on_sheet +
          " · " + quantity(edge.formula_cells) + " células com referências",
          "muted"
        ));
      }
      sub.append(body);
      panel.append(sub);
    }
    const sheetList = (context.sheets || []).slice().sort(
      (a, b) => Number(b.formula_count || 0) - Number(a.formula_count || 0)
    );
    const sheetGroup = $node("details", null, "report-group");
    sheetGroup.append($node("summary",
      "Abas identificadas · " + quantity(context.sheets?.length || 0)
    ));
    const contents = $node("div", null, "report-group-body");
    for (const sh of sheetList.slice(0, 41)) {
      const row = $node("p",
        sh.name + " · " + (
          sh.formula_count === null
            ? "quantidade de fórmulas não disponível"
            : quantity(sh.formula_count) + " fórmulas"
        ), "muted");
      contents.append(row);
      if (Array.isArray(sh.possible_headers) && sh.possible_headers.length) {
        contents.append($node("p",
          "Possíveis cabeçalhos: " + sh.possible_headers.slice(0, 8).join(" · "),
          "finding-locations"
        ));
      }
    }
    sheetGroup.append(contents);
    panel.append(sheetGroup);
    const caveats = $node("details", null, "finding-extra");
    caveats.append($node("summary", "Limitações e privacidade"));
    const list = $node("ul");
    for (const note of context.limitations || []) list.append($node("li", note));
    list.append($node("li",
      "O SheetOpt não contata modelos de IA nesta etapa. " +
      "Nomes de abas e cabeçalhos podem conter informações internas."
    ));
    caveats.append(list);
    panel.append(caveats);
    addButton(panel, "Exportar contexto JSON", () => {
      const content = JSON.stringify({
        generated_at: new Date().toISOString(),
        context,
        ai_transmission: "none"
      }, null, 2);
      downloadBlob("sheetopt-contexto.json",
        new Blob([content], {type: "application/json;charset=utf-8"}));
    });
    root.append(panel);
  }

  function renderPerf003Review(root, report) {
    const findings = (report.findings || [])
      .filter((finding) => finding.rule_id === "PERF-003")
      .slice()
      .sort((a, b) =>
        Number(b.evidence?.weighted_occurrences || 0) -
        Number(a.evidence?.weighted_occurrences || 0)
      );
    if (!findings.length) return;
    const panel = $node("details", null, "report-details");
    panel.append($node("summary",
      "PERF-003 · Referências a colunas inteiras · " + quantity(findings.length) +
      " oportunidades de revisão"
    ));
    panel.append($node("p",
      "Estas ocorrências podem causar cálculos repetidos. As contagens são estimativas " +
      "baseadas em padrões de fórmulas, não medições de tempo nem número de células processadas. " +
      "Não há reescrita automática: limitar um intervalo sem conhecer o crescimento dos dados " +
      "pode alterar o resultado futuro.",
      "muted"
    ));
    const list = $node("div", null, "review-opportunities");
    for (const finding of findings.slice(0, 8)) {
      const card = $node("div", null, "finding");
      card.append($node("strong",
        String(finding.evidence?.reference || "Intervalo não identificado")
      ));
      card.append($node("p", finding.message, "muted"));
      if (Array.isArray(finding.locations) && finding.locations.length) {
        card.append($node("p",
          "Exemplos: " + finding.locations.slice(0, 5).join(", "), "finding-locations"
        ));
      }
      card.append($node("p",
        "Para transformar com segurança: identificar a aba de origem, o último dado " +
        "utilizado, a política de novas linhas, fórmulas dependentes e os tipos de dados. " +
        "Depois comparar o intervalo afetado na cópia.",
        "muted"
      ));
      list.append(card);
    }
    if (findings.length > 8) {
      list.append($node("p",
        "Outros " + quantity(findings.length - 8) + " intervalos estão no relatório " +
        "completo (PDF/JSON) e em Explorar alertas por regra.",
        "muted"
      ));
    }
    panel.append(list);
    root.append(panel);
  }

  function renderAggregationPlanning(root, result) {
    const suggestions = result.aggregation_opportunities || [];
    const panel = $node("details", null, "report-details");
    panel.append($node("summary",
      "Plano de agregações compartilhadas (QUERY) · " + quantity(suggestions.length)
    ));
    panel.append($node("p",
      "O SheetOpt agrupou padrões semelhantes de SUMIFS por aba de origem, " +
      "coluna somada e colunas de critérios. São propostas arquiteturais para revisão — " +
      "não são fórmulas validadas nem mudanças aplicáveis nesta versão.",
      "muted"
    ));
    if (!suggestions.length) {
      panel.append($node("p",
        "Nenhum agrupamento elegível foi reconhecido nos alertas PERF-002 do diagnóstico. " +
        "Isso não significa que a planilha não possa ser otimizada.",
        "muted"
      ));
      root.append(panel);
      return;
    }
    const list = $node("div", null, "review-opportunities");
    for (const suggestion of suggestions) {
      const card = $node("details", null, "report-group");
      const summary = $node("summary");
      summary.append(
        $node("strong", suggestion.source_sheet + " · soma de " +
          suggestion.measure_column + " por " + suggestion.group_columns.join(", ")),
        $node("span", quantity(suggestion.estimated_pattern_occurrences) +
          " ocorrências estimadas", "pill")
      );
      card.append(summary);
      const contents = $node("div", null, "report-group-body");
      contents.append($node("p",
        "Padrões identificados: " + quantity(suggestion.pattern_count) +
        ". A contagem pode se sobrepor entre grupos, não equivale ao número " +
        "de células que seriam corrigidas e não mede ganho de performance.",
        "muted"
      ));
      contents.append($node("p", suggestion.explanation, "muted"));
      contents.append($node("pre", suggestion.query_shape, "formula-diff"));
      if (Array.isArray(suggestion.example_cells) && suggestion.example_cells.length) {
        contents.append($node("p",
          "Exemplos: " + suggestion.example_cells.join(", "), "finding-locations"
        ));
      }
      const checks = $node("details", null, "finding-extra");
      checks.append($node("summary", "Condições que precisam ser validadas"));
      const ul = $node("ul");
      for (const requirement of suggestion.requires_validation || []) {
        ul.append($node("li", requirement));
      }
      checks.append(ul);
      contents.append(checks);
      card.append(contents);
      list.append(card);
    }
    panel.append(list);
    root.append(panel);
  }

  function renderCandidates(root, result, token) {
    const candidates = result.optimization_candidates || [];
    if (!result.clone) return;
    const block = $node("details", null, "report-details");
    block.append($node("summary",
      "Otimizações experimentais na cópia · " + quantity(candidates.length)
    ));
    const text = $node("p", candidates.length
      ? "Primeira regra: duplicação de agregações escalares idênticas na mesma fórmula. " +
        "O teste altera uma célula da CÓPIA, compara valor e formatos, e reverte em caso de divergência. " +
        "Isso não valida a planilha inteira e não mede aceleração."
      : "Nenhuma fórmula corresponde à regra experimental OPT-LET-001. " +
        "Isso não significa ausência de oportunidades: as referências de colunas " +
        "inteiras são listadas abaixo para revisão, sem alteração automática.");
    text.className = "muted";
    block.append(text);
    const cloneId = result.clone.id;
    for (const candidate of candidates) {
      const item = $node("div", null, "finding");
      item.append($node("strong", candidate.rule_id + " · " + candidate.a1));
      item.append($node("p", candidate.description, "muted"));
      const pair = $node("details", null, "finding-extra");
      pair.append($node("summary", "Ver fórmulas antes/depois"));
      pair.append($node("pre", "ANTES: " + candidate.before + "\n\nDEPOIS: " + candidate.after, "formula-diff"));
      item.append(pair);
      const response = $node("p", "Ainda não testada.", "muted");
      addButton(item, "Testar alteração na cópia", async (event) => {
        if (!window.confirm(
          "Este teste alterará UMA célula apenas da cópia e tentará revertê-la se houver divergência. Continuar?"
        )) return;
        const button = event.currentTarget;
        button.disabled = true;
        button.textContent = "Validando...";
        try {
          const apiResponse = await fetch("/v1/optimizations/test", {
            method: "POST",
            headers: {
              "Authorization": "Bearer " + token,
              "Content-Type": "application/json"
            },
            body: JSON.stringify({clone_id: cloneId, candidate_id: candidate.id}),
            cache: "no-store"
          });
          const payload = await apiResponse.json().catch(() => ({}));
          if (!apiResponse.ok) {
            throw new Error(typeof payload.detail === "string"
              ? payload.detail : "Não foi possível testar a alteração (HTTP " + apiResponse.status + ").");
          }
          const messages = {
            validated_cell_only: "Célula validada localmente na cópia (sem medição de performance).",
            rejected: "Proposta rejeitada; nenhuma fórmula modificada.",
            reverted: "Validação falhou; a fórmula anterior foi restaurada na cópia.",
            manual_review_required: "ALERTA: estado da cópia não confirmado. Verifique manualmente."
          };
          response.textContent = (messages[payload.status] || payload.status) +
            " " + (payload.message || payload.reason || "");
          response.className = payload.status === "manual_review_required" ? "warning" : "muted";
          button.textContent = "Teste encerrado";
        } catch (error) {
          response.textContent = "Resultado incerto: " + error.message +
            " Verifique a cópia antes de qualquer nova tentativa.";
          response.className = "warning";
          button.textContent = "Rever cópia";
        }
      });
      item.append(response);
      block.append(item);
    }
    root.append(block);
  }
  function renderReport(result, token) {
    const report = result.report;
    const root = document.getElementById("results");
    root.replaceChildren();
    root.hidden = false;
    const header = $node("div", null, "report-header");
    const heading = $node("div");
    heading.append($node("span", "DIAGNÓSTICO CONCLUÍDO", "eyebrow"));
    heading.append($node("h3", report.title));
    header.append(heading);
    const toggle = $node("details", null, "report-summary-note");
    toggle.append($node("summary", "Informações sobre a análise"));
    toggle.append($node("p",
      "Os alertas representam oportunidades a investigar. Nenhuma fórmula foi otimizada; " +
      "o ganho de desempenho ainda não foi medido."
    ));
    header.append(toggle);
    root.append(header);

    const metrics = $node("div", null, "report-metrics");
    addMetric(metrics, "Abas", report.sheet_count);
    addMetric(metrics, "Fórmulas", report.formula_count);
    addMetric(metrics, "Padrões", report.pattern_count);
    addMetric(metrics, "Alertas", report.findings.length);
    root.append(metrics);

    const counts = $node("div", null, "report-severity-summary");
    for (const severity of severityOrder) {
      const count = report.findings.filter((finding) => finding.severity === severity).length;
      if (count) counts.append($node("span",
        severityNames[severity] + ": " + quantity(count),
        "severity " + severity
      ));
    }
    if (counts.children.length) root.append(counts);

    if (result.status === "no_formulas" ||
        (result.status === "diagnosed_only" && !report.formula_count)) {
      root.append($node("p", "Sem fórmulas para otimizar.", "muted"));
    } else if (result.status === "diagnosed_only") {
      root.append($node("p", "Somente diagnóstico; nenhuma cópia adicional foi criada.", "muted"));
    } else if (result.status === "clone_timeout") {
      root.append($node("p",
        result.clone_message || "Resultado da cópia desconhecido. Verifique seu Google Drive.",
        "warning"
      ));
    } else if (result.clone) {
      const cloneUrl = validCloneUrl(result.clone.url);
      if (cloneUrl) {
        const link = $node("a", "Abrir cópia de trabalho ↗", "clone-link");
        link.href = cloneUrl;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        root.append(link);
      }
    }
    root.append($node("p", "Otimizações aplicadas: 0 · Merge indisponível até a validação.", "muted"));

    const tools = $node("div", null, "report-toolbar");
    const downloadPdf = addButton(tools, "Exportar PDF", async (event) => {
      const button = event.currentTarget;
      button.disabled = true;
      button.textContent = "Gerando PDF...";
      try {
        const response = await fetch("/v1/reports/pdf", {
          method: "POST",
          headers: {
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json"
          },
          body: JSON.stringify({
            report,
            status: result.status || "diagnosed",
            events: result.events || []
          }),
          cache: "no-store"
        });
        if (!response.ok) throw new Error("Falha na exportação do PDF (HTTP " + response.status + ").");
        const blob = await response.blob();
        if (blob.type !== "application/pdf") throw new Error("Resposta PDF inválida.");
        downloadBlob("sheetopt-diagnostico.pdf", blob);
      } catch (err) {
        const status = document.getElementById("notice");
        status.textContent = err.message;
        status.classList.add("visible");
      } finally {
        button.disabled = false;
        button.textContent = "Exportar PDF";
      }
    });
    downloadPdf.title = "Gera um relatório usando o diagnóstico que já foi calculado.";
    addButton(tools, "Exportar JSON", () => {
      const json = JSON.stringify({
        generated_at: new Date().toISOString(),
        report,
        status: result.status || "diagnosed",
        events: result.events || [],
        clone: result.clone || null,
        aggregation_opportunities: result.aggregation_opportunities || [],
        context: result.context || null
      }, null, 2);
      downloadBlob("sheetopt-diagnostico.json",
        new Blob([json], {type: "application/json;charset=utf-8"}));
    });
    root.append(tools);
    root.append($node("p",
      "Os arquivos exportados podem conter nomes de abas, referências e trechos de fórmulas. " +
      "Compartilhe apenas quando apropriado.",
      "report-privacy"
    ));
    buildTimeline(root, result.events || []);

    const detail = $node("details", null, "report-details");
    detail.append($node("summary", "Explorar alertas por regra · " + quantity(report.findings.length)));
    const toolsFilter = $node("div", null, "report-filters");
    const search = $node("input");
    search.type = "search";
    search.placeholder = "Buscar regra, fórmula, aba ou mensagem";
    search.setAttribute("aria-label", "Buscar alertas");
    const select = $node("select");
    select.setAttribute("aria-label", "Filtrar severidade");
    for (const [key, title] of [
      ["", "Todas as prioridades"], ...severityOrder.map(key => [key, severityNames[key]])
    ]) {
      const option = $node("option", title);
      option.value = key;
      select.append(option);
    }
    toolsFilter.append(search, select);
    detail.append(toolsFilter);
    const groups = $node("div", null, "report-groups");
    detail.append(groups);
    const filter = () => renderGroups(
      groups, report, select.value, search.value.trim().toLocaleLowerCase()
    );
    select.addEventListener("change", filter);
    search.addEventListener("input", filter);
    detail.addEventListener("toggle", () => {
      if (detail.open && !detail.dataset.loaded) {
        detail.dataset.loaded = "1";
        filter();
      }
    });
    root.append(detail);
    renderCandidates(root, result, token);
    renderWorkbookContext(root, result);
    renderAiAssistant(root, result, token);
    renderEvidenceHistory(root, token);
    renderPerf003Review(root, report);
    renderAggregationPlanning(root, result);
    root.scrollIntoView({behavior: "smooth", block: "start"});
  }
  window.SheetOptReports = { renderReport };
})();
