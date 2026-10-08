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
  const contentType = response.headers.get("content-type") || "";
  const data = contentType.includes("application/json")
    ? await response.json().catch(() => ({}))
    : {};
  if (!response.ok) {
    const detail = typeof data.detail === "string" ? data.detail : null;
    const generic = response.status >= 500
      ? "Falha interna no servidor (HTTP " + response.status +
        "). Veja os logs com: docker compose logs --tail=100 sheetopt"
      : "Requisição recusada (HTTP " + response.status + ").";
    throw new Error(detail && detail !== "Internal Server Error" ? detail : generic);
  }
  if (!data || typeof data !== "object" || !Object.keys(data).length) {
    throw new Error("O servidor respondeu, mas não retornou um relatório JSON válido.");
  }
  return data;
}
async function refresh() {
  const data = await request("/v1/settings");
  $("google-status").textContent = data.google.oauth_connected && data.google.mode === "oauth"
    ? "OAuth conectado" : data.google.mode === "service_account" ? "Service Account" : "Não configurado";
  $("google-email").textContent = data.google.email || "";
  $("google-connect").disabled = !data.google.oauth_client_configured;
  $("google-disconnect").disabled = !data.google.oauth_connected;
  $("oauth-status").textContent = data.google.oauth_connected
    ? "Conta conectada · método ativo: OAuth 2.0"
    : data.google.oauth_client_configured ? "Cliente OAuth salvo; clique em Conectar com Google."
    : "Carregue seu arquivo OAuth primeiro.";
  $("oauth-redirect").textContent = data.google.oauth_redirect_uri
    ? "URI de retorno: " + data.google.oauth_redirect_uri : "";
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
  if (data.status === "no_formulas" || (data.status === "diagnosed_only" && !report.formula_count)) {
    line("p", "Nenhuma fórmula encontrada. Esta etapa não executa otimizações estruturais.", node);
  } else if (data.status === "diagnosed_only") {
    line("p", "Diagnóstico somente leitura concluído; nenhuma nova cópia foi criada.", node);
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

$("google-oauth-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  try {
    toggleBusy(form, true);
    const file = $("google-oauth-file").files[0];
    if (!file || file.size > 1024 * 1024) throw new Error("Selecione um JSON de até 1 MB.");
    const parsed = JSON.parse(await file.text());
    await request("/v1/settings/google/oauth-client", "PUT", { client_config: parsed });
    $("google-oauth-file").value = "";
    await refresh();
    notice("Cliente OAuth salvo. Clique em Conectar com Google.");
  } catch (err) { notice(err.message); }
  finally { toggleBusy(form, false); }
});
$("google-connect").addEventListener("click", async () => {
  const popup = window.open("about:blank", "sheetopt_google_oauth", "width=580,height=720");
  if (!popup) { notice("Permita pop-ups para conectar com Google."); return; }
  try {
    const result = await request("/v1/google/oauth/start", "POST");
    popup.location.replace(result.authorization_url);
    notice("Conclua a autorização na janela Google. O status será atualizado automaticamente.");
    let attempts = 0;
    const timer = window.setInterval(async () => {
      if (++attempts > 90) { window.clearInterval(timer); return; }
      try {
        await refresh();
        if ($("oauth-status").textContent.includes("Conta conectada")) {
          window.clearInterval(timer);
          notice("Google conectado! Já pode analisar suas planilhas.");
        } else if (popup.closed) {
          window.clearInterval(timer);
        }
      } catch (_) { /* Keep pending until the next status check. */ }
    }, 2000);
  } catch (err) {
    popup.close();
    notice(err.message);
  }
});
$("google-refresh").addEventListener("click", async () => {
  try { await refresh(); notice("Status da conexão atualizado."); }
  catch (err) { notice(err.message); }
});
$("google-disconnect").addEventListener("click", async () => {
  if (!window.confirm("Desconectar a conta Google desta instalação do SheetOpt?")) return;
  try {
    await request("/v1/settings/google/oauth", "DELETE");
    await refresh();
    notice("Tokens OAuth apagados da instalação. Você também pode revogar o acesso na sua Conta Google.");
  } catch (err) { notice(err.message); }
});

$("diagnose-only").addEventListener("click", async () => {
  const form = $("analyze-form");
  if (!$("spreadsheet").reportValidity()) return;
  try {
    toggleBusy(form, true);
    notice("Analisando fórmulas sem criar outra cópia...");
    const report = await request("/v1/analyze", "POST", {
      spreadsheet_url: $("spreadsheet").value.trim()
    });
    showReport({ report, status: "diagnosed_only", clone: null });
    notice("Diagnóstico concluído. Nenhuma cópia foi criada.");
  } catch (err) { notice(err.message); }
  finally { toggleBusy(form, false); }
});
