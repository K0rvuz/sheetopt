"use strict";
let adminToken = "";
const $ = (id) => document.getElementById(id);
const notice = (message) => { $("notice").textContent = message; $("notice").classList.add("visible"); };
async function request(path, method = "GET", body) {
  const response = await fetch(path, {
    method,
    headers: { Authorization: "Bearer " + adminToken, ...(body ? { "Content-Type": "application/json" } : {}) },
    body: body ? JSON.stringify(body) : undefined,
    cache: "no-store"
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Falha na requisição.");
  return data;
}
async function refresh() {
  const data = await request("/v1/settings");
  $("google-status").textContent = data.google.configured ? "Configurado" : "Não configurado";
  $("google-email").textContent = data.google.email || "";
  $("ai-status").textContent = data.ai.provider === "disabled" ? "Desativada" : data.ai.provider;
  $("ai-provider").value = data.ai.provider || "disabled";
  $("ai-endpoint").value = data.ai.endpoint || "";
  $("ai-model").value = data.ai.model || "";
  updateAiFields();
}
function updateAiFields() {
  $("ai-extra").hidden = $("ai-provider").value === "disabled";
}
function line(tag, text, parent) {
  const el = document.createElement(tag);
  el.textContent = text;
  parent.append(el);
  return el;
}
function showReport(data) {
  const node = $("results");
  node.replaceChildren();
  node.hidden = false;
  const report = data.report;
  line("h3", report.title, node);
  line("p", report.sheet_count + " abas · " + report.formula_count + " fórmulas · " + report.pattern_count + " padrões · " + report.findings.length + " alertas", node);
  if (data.status === "no_formulas") {
    line("p", "Nenhuma fórmula encontrada. Não foi criada cópia; esta etapa não executa otimizações estruturais.", node);
  } else if (data.clone) {
    line("p", "Diagnóstico concluído. Cópia criada, sem alterações nas fórmulas.", node);
    const a = line("a", "Abrir cópia de trabalho ↗", node);
    const url = new URL(data.clone.url);
    if (url.protocol === "https:" && url.hostname === "docs.google.com") {
      a.href = url.href;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
    } else {
      a.removeAttribute("href");
    }
  }
  line("p", "Otimizações aplicadas: 0 · Merge indisponível até a implementação do validador.", node);
  report.findings.forEach((finding) => {
    const card = document.createElement("div");
    card.className = "finding";
    line("strong", finding.rule_id + " · " + finding.title, card);
    line("p", finding.message, card);
    line("small", "Prioridade: " + finding.severity, card);
    node.append(card);
  });
}
function toggleBusy(form, busy) {
  for (const control of form.querySelectorAll("button, input, select")) control.disabled = busy;
}
$("login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  adminToken = $("token").value.trim();
  try {
    await refresh();
    $("login").hidden = true;
    $("workspace").hidden = false;
    $("token").value = "";
    notice("Acesso autorizado.");
  } catch (err) {
    adminToken = "";
    notice(err.message);
  }
});
$("google-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  try {
    toggleBusy(form, true);
    const file = $("google-file").files[0];
    if (!file || file.size > 1024 * 1024) throw new Error("Selecione um JSON de até 1 MB.");
    const parsed = JSON.parse(await file.text());
    await request("/v1/settings/google", "PUT", { service_account: parsed });
    $("google-file").value = "";
    await refresh();
    notice("Credenciais Google salvas de forma criptografada.");
  } catch (err) { notice(err.message); }
  finally { toggleBusy(form, false); }
});
$("ai-provider").addEventListener("change", updateAiFields);
$("ai-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  try {
    toggleBusy(form, true);
    await request("/v1/settings/ai", "PUT", {
      provider: $("ai-provider").value,
      endpoint: $("ai-provider").value === "disabled" ? "" : $("ai-endpoint").value.trim(),
      model: $("ai-provider").value === "disabled" ? "" : $("ai-model").value.trim(),
      api_key: $("ai-provider").value === "disabled" ? "" : $("ai-key").value
    });
    $("ai-key").value = "";
    await refresh();
    notice("Preferências de IA armazenadas. A execução de IA será adicionada em outra etapa.");
  } catch (err) { notice(err.message); }
  finally { toggleBusy(form, false); }
});
$("analyze-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  try {
    toggleBusy(form, true);
    notice("Lendo planilha e criando uma cópia quando houver fórmulas...");
    const result = await request("/v1/workbooks/analyze", "POST", { spreadsheet_url: $("spreadsheet").value.trim() });
    showReport(result);
    notice("Diagnóstico concluído. A planilha original não foi modificada.");
  } catch (err) { notice(err.message); }
  finally { toggleBusy(form, false); }
});
