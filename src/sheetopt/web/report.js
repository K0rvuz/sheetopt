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
    const panel = $node("details", null, "report-details");
    panel.append($node("summary", "IA contextual (opcional) · propostas para revisão"));
    panel.append($node("p",
      "A IA pode considerar relações entre abas, padrões SUMIFS e gargalos. " +
      "Não recebe fórmulas completas ou valores das linhas. Nenhuma planilha " +
      "é modificada e o envio só ocorre após prévia e autorização explícita.",
      "muted"
    ));
    const configLink = $node("a", "Configurar provedor na seção Inteligência artificial");
    configLink.href = "#ai";
    panel.append(configLink);
    const controls = $node("div", null, "report-filters");
    const focus = $node("select");
    focus.setAttribute("aria-label", "Escolher aba para análise por IA");
    const all = $node("option", "Visão geral do documento");
    all.value = "";
    focus.append(all);
    for (const sh of (result.context.sheets || []).slice(0, 80)) {
      const opt = $node("option", sh.name);
      opt.value = sh.name;
      focus.append(opt);
    }
    controls.append(focus);
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
    controls.append(investigation);
    panel.append(controls);

    const labels = $node("label", null, "ai-check");
    const includeNames = $node("input");
    includeNames.type = "checkbox";
    labels.append(includeNames, document.createTextNode(
      "Incluir nomes de abas e possíveis cabeçalhos no contexto enviado"
    ));
    panel.append(labels);

    const previewButton = addButton(panel, "Visualizar contexto que será enviado", async () => {
      previewButton.disabled = true;
      runButton.disabled = true;
      consent.checked = false;
      previewHash = null;
      previewInfo.replaceChildren();
      try {
        const response = await fetch("/v1/ai/preview", {
          method: "POST",
          headers: {
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json"
          },
          body: JSON.stringify(packetRequest()),
          cache: "no-store"
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(typeof data.detail === "string"
            ? data.detail : "Prévia indisponível (HTTP " + response.status + ").");
        }
        previewHash = data.preview_hash;
        previewInfo.append($node("p",
          data.ready
            ? "Destino: " + data.destination + " · Modelo: " + data.model
            : "IA desativada. Configure seu próprio provedor antes de executar.",
          "muted"
        ));
        previewInfo.append($node("p",
          "Volume do pacote: " + quantity(data.packet_chars) +
          " caracteres. Nenhuma chamada ao modelo foi feita.",
          "muted"
        ));
        const details = $node("details", null, "finding-extra");
        details.open = true;
        details.append($node("summary", "Inspecionar JSON exato do contexto"));
        details.append($node("pre", JSON.stringify(data.packet, null, 2), "formula-diff"));
        previewInfo.append(details);
      const references = (data.packet?.knowledge_sources || []);
      if (references.length) {
        const citations = $node("details", null, "finding-extra");
        citations.append($node("summary", "Documentação oficial recuperada · " + references.length));
        for (const source of references) {
          const link = $node("a", source.source_id + " — " + source.title);
          link.href = source.source_url;
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          citations.append(link, $node("p", source.guidance, "muted"));
        }
        previewInfo.append(citations);
      }
      } catch (error) {
        previewInfo.append($node("p", error.message, "warning"));
      } finally {
        previewButton.disabled = false;
      }
    });

    const probe = addButton(panel, "Investigar contexto local (sem IA)", async (event) => {
      const button = event.currentTarget;
      button.disabled = true;
      try {
        const response = await fetch("/v1/ai/investigate", {
          method: "POST",
          headers: {"Authorization": "Bearer " + token, "Content-Type": "application/json"},
          body: JSON.stringify(packetRequest()),
          cache: "no-store"
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(
          typeof data.detail === "string" ? data.detail : "Investigação indisponível."
        );
        previewInfo.replaceChildren(
          $node("p", "Contexto investigado localmente. Nenhuma IA ou Google API foi chamada.", "muted")
        );
        const details = $node("details", null, "finding-extra");
        details.open = true;
        details.append($node("summary", "Ver contexto e referências oficiais"));
        details.append($node("pre", JSON.stringify(data.packet, null, 2), "formula-diff"));
        previewInfo.append(details);
        previewHash = null;
        consent.checked = false;
        runButton.disabled = true;
      } catch (error) {
        previewInfo.replaceChildren($node("p", error.message, "warning"));
      } finally {
        button.disabled = false;
      }
    });

    const previewInfo = $node("div", null, "ai-preview");
    panel.append(previewInfo);
    const approve = $node("label", null, "ai-check");
    const consent = $node("input");
    consent.type = "checkbox";
    approve.append(consent, document.createTextNode(
      "Li a prévia e autorizo este envio ao provedor configurado."
    ));
    panel.append(approve);

    let previewHash = null;
    const reset = () => {
      previewHash = null;
      consent.checked = false;
      runButton.disabled = true;
      previewInfo.replaceChildren($node("p",
        "Os parâmetros mudaram. Gere uma nova prévia antes de enviar.", "muted"
      ));
    };
    focus.addEventListener("change", reset);
    investigation.addEventListener("change", reset);
    includeNames.addEventListener("change", reset);
    consent.addEventListener("change", () => {
      runButton.disabled = !(consent.checked && previewHash);
    });
    const packetRequest = () => ({
      report: result.report,
      context: result.context || null,
      opportunities: result.aggregation_opportunities || [],
      focus_sheet: focus.value || null,
      investigation: investigation.value,
      include_identifiers: includeNames.checked,
    });

    const resultArea = $node("div", null, "ai-suggestions");
    const runButton = addButton(panel, "Gerar propostas com IA", async () => {
      if (!consent.checked || !previewHash) return;
      runButton.disabled = true;
      runButton.textContent = "Aguardando provedor de IA...";
      try {
        const response = await fetch("/v1/ai/suggest", {
          method: "POST",
          headers: {
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json"
          },
          body: JSON.stringify({
            ...packetRequest(),
            consent: true,
            preview_hash: previewHash
          }),
          cache: "no-store"
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(typeof data.detail === "string"
            ? data.detail : "Erro no provedor de IA (HTTP " + response.status + ").");
        }
        resultArea.replaceChildren();
        resultArea.append($node("p", data.result.summary, "muted"));
        for (const proposal of data.result.proposals || []) {
          const section = $node("details", null, "report-group");
          section.append($node("summary", proposal.title));
          const inner = $node("div", null, "report-group-body");
          inner.append($node("p", proposal.rationale, "muted"));
          inner.append($node("p",
            "Impacto hipotético: " + proposal.impact +
            " · Risco: " + proposal.risk +
            " · Abas: " + (proposal.target_sheets || []).join(", "), "muted"
          ));
          const steps = $node("ul");
          for (const step of proposal.validation_steps || []) {
            steps.append($node("li", step));
          }
          inner.append($node("strong", "Validação obrigatória antes de alterar qualquer fórmula"));
          inner.append(steps);
          section.append(inner);
          resultArea.append(section);
        }
        const missing = data.result.missing_context || [];
        if (missing.length) {
          const todo = $node("details", null, "report-group");
          todo.append($node("summary", "Informações adicionais necessárias"));
          const list = $node("ul");
          for (const item of missing) list.append($node("li", item));
          todo.append(list);
          resultArea.append(todo);
        }
        resultArea.append($node("p",
          "Sugestões não verificadas. Ganho de desempenho não medido; merge indisponível.",
          "warning"
        ));
        previewHash = null;
        consent.checked = false;
      } catch (error) {
        resultArea.replaceChildren($node("p", error.message, "warning"));
      } finally {
        runButton.disabled = true;
        runButton.textContent = "Gerar propostas com IA";
      }
    });
    runButton.disabled = true;
    panel.append(resultArea);
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
