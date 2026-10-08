"use strict";

// Minimal dependency-free browser contract for the contextual AI section.
// Tests verify pending-state transitions without contacting Google or Ollama.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const WEB_DIR = path.resolve(__dirname, "../src/sheetopt/web");

class Element {
  constructor(tag, content = "") {
    this.tag = tag;
    this.textContent = content;
    this.children = [];
    this.events = {};
    this.attributes = {};
    this.dataset = {};
    this.className = "";
    this.hidden = false;
    this.disabled = false;
    this.checked = false;
    this.value = "";
    this.classList = {
      add: (...names) => {
        this.className = [...new Set([...this.className.split(" "), ...names])].join(" ").trim();
      },
      remove: (...names) => {
        this.className = this.className.split(" ").filter(name => !names.includes(name)).join(" ");
      },
      contains: (name) => this.className.split(" ").includes(name)
    };
  }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children = [...items]; }
  setAttribute(name, value) { this.attributes[name] = value; }
  addEventListener(event, listener) {
    (this.events[event] ||= []).push(listener);
  }
  trigger(event = "click") {
    // Browser event listeners run synchronously; only their async work waits.
    return Promise.all(
      (this.events[event] || []).map(listener =>
        listener({ currentTarget: this, target: this })
      )
    );
  }
  scrollIntoView() {}
  click() {}
  remove() {}
}

function descendants(node) {
  const children = node?.children || [];
  return [node, ...children.flatMap(descendants)];
}

function setup(fetchImpl) {
  const root = new Element("div");
  const notice = new Element("div");
  const timers = new Map();
  const downloads = [];
  let nextTimer = 0;
  const window = {
    setInterval: (callback) => {
      const id = ++nextTimer;
      timers.set(id, callback);
      return id;
    },
    clearInterval: (id) => timers.delete(id),
    setTimeout: () => 0
  };
  const document = {
    body: new Element("body"),
    getElementById: (id) => id === "results" ? root : notice,
    createElement: (tag) => new Element(tag),
    createTextNode: (value) => new Element("text", String(value))
  };
  class DownloadURL extends URL {}
  DownloadURL.createObjectURL = (blob) => { downloads.push(blob); return "blob:synthetic"; };
  DownloadURL.revokeObjectURL = () => {};
  vm.runInNewContext(fs.readFileSync(path.join(WEB_DIR, "report.js"), "utf8"), {
    window, document, fetch: fetchImpl, URL: DownloadURL, Blob, Date,
    console, setTimeout
  });
  const report = {
    title: "Synthetic workbook", sheet_count: 2, formula_count: 15,
    pattern_count: 2, findings: []
  };
  const context = {
    coverage: "formula_snapshot", sheet_count: 2, formula_count: 15,
    edge_count_total: 1, dynamic_formula_count: 0,
    sheets: [
      { name: "Overview", formula_count: 10, possible_headers: [] },
      { name: "Data", formula_count: 5, possible_headers: [] }
    ],
    edges: [{ from_sheet: "Overview", depends_on_sheet: "Data", formula_cells: 9 }],
    hotspots: [], limitations: []
  };
  window.SheetOptReports.renderReport({
    report, context, aggregation_opportunities: [], status: "diagnosed_only",
    events: [], clone: null
  }, "token-only-in-test");
  const find = (predicate) => {
    // Newly returned proposals are mounted asynchronously after setup().
    const match = descendants(root).find(predicate);
    assert.ok(match, "Expected element to exist.");
    return match;
  };
  return { find, root, timers, downloads };
}

test("AI UI shows scoped checkboxes and remains idle before approval", () => {
  const ui = setup(async () => { throw Error("Unexpected network call"); });
  const checkboxes = descendants(ui.root).filter(x => x.tag === "input" && x.type === "checkbox");
  assert.equal(checkboxes.length, 3);
  for (const checkbox of checkboxes) {
    assert.ok(descendants(ui.root).some(x => x.classList.contains("ai-checkbox") &&
      descendants(x).includes(checkbox)));
  }
  const button = ui.find(x => x.tag === "button" && x.textContent === "Gerar propostas com IA");
  assert.equal(button.disabled, true);
  const progress = ui.find(x => x.classList.contains("ai-progress"));
  assert.equal(progress.hidden, true);
  const css = fs.readFileSync(path.join(WEB_DIR, "ui.css"), "utf8");
  assert.match(css, /\.ai-checkbox input\[type="checkbox"\]\s*\{/);
  assert.match(css, /min-height:17px/);
  assert.match(css, /@media\(prefers-reduced-motion:reduce\)/);
});

test("AI UI displays indeterminate activity, elapsed timer, locks controls and completes", async () => {
  let resolveSuggestion;
  let suggestCalls = 0;
  const ui = setup(async (url) => {
    if (url === "/v1/ai/preview") {
      return {
        ok: true, json: async () => ({
          preview_hash: "synthetic-hash", ready: true, destination: "host.docker.internal",
          model: "qwen3.5:4b", packet_chars: 120,
          packet: { knowledge_sources: [] }
        })
      };
    }
    if (url === "/v1/ai/suggest") {
      suggestCalls++;
      return new Promise(resolve => { resolveSuggestion = resolve; });
    }
    throw Error("Unexpected network call: " + url);
  });
  const preview = ui.find(x => x.tag === "button" && x.textContent === "Visualizar pacote para IA");
  const consent = ui.find(x => x.tag === "input" && x.type === "checkbox" &&
    descendants(ui.root).some(p => p.classList.contains("ai-consent") &&
      descendants(p).includes(x)));
  const run = ui.find(x => x.tag === "button" && x.textContent === "Gerar propostas com IA");
  const progress = ui.find(x => x.classList.contains("ai-progress"));
  const focus = ui.find(x => x.tag === "select" &&
    x.attributes["aria-label"] === "Aba para análise por IA");
  await preview.trigger();
  assert.equal(consent.disabled, false);
  consent.checked = true;
  await consent.trigger("change");
  assert.equal(run.disabled, false);

  const pending = run.trigger();
  assert.equal(progress.hidden, false);
  assert.equal(progress.classList.contains("is-running"), true);
  assert.equal(ui.timers.size, 1);
  assert.equal(run.disabled, true);
  assert.equal(focus.disabled, true);
  assert.equal(suggestCalls, 1);
  const bar = ui.find(x => x.classList.contains("ai-progress-track"));
  assert.equal(bar.attributes.role, "progressbar");
  assert.equal(bar.attributes["aria-valuenow"], undefined);

  resolveSuggestion({
    ok: true,
    json: async () => ({
      result: { summary: "Potential repeated sums", proposals: [],
        missing_context: [] }
    })
  });
  await pending;
  assert.equal(ui.timers.size, 0);
  assert.equal(progress.classList.contains("is-complete"), true);
  assert.equal(progress.classList.contains("is-running"), false);
  assert.equal(focus.disabled, false);
  assert.equal(run.disabled, true);
  assert.equal(consent.checked, false);
  assert.equal(ui.find(x => x.tag === "h4" && x.textContent === "Propostas recebidas").tag, "h4");
});

test("AI UI ends animation on provider error without pretending success", async () => {
  const ui = setup(async (url) => {
    if (url === "/v1/ai/preview") {
      return { ok: true, json: async () => ({
        preview_hash: "hash", ready: true, packet: {}, destination: "local",
        model: "qwen", packet_chars: 2
      }) };
    }
    if (url === "/v1/ai/suggest") {
      return { ok: false, status: 502, json: async () => ({ detail: "AI provider unavailable" }) };
    }
    throw Error("Unexpected request");
  });
  const preview = ui.find(x => x.tag === "button" && x.textContent === "Visualizar pacote para IA");
  await preview.trigger();
  const consent = ui.find(x => x.tag === "input" && x.type === "checkbox" &&
    descendants(ui.root).some(p => p.classList.contains("ai-consent") &&
      descendants(p).includes(x)));
  consent.checked = true;
  await consent.trigger("change");
  const run = ui.find(x => x.tag === "button" && x.textContent === "Gerar propostas com IA");
  await run.trigger();
  const progress = ui.find(x => x.classList.contains("ai-progress"));
  assert.equal(progress.classList.contains("is-running"), false);
  assert.equal(ui.timers.size, 0);
  assert.equal(run.disabled, true);
  assert.equal(ui.find(x => x.tag === "strong" && x.textContent === "Falha na consulta").tag, "strong");
});

test("complete AI exports preserve the full structured response and preview context", async () => {
  let postedPDF;
  const packet = {
    packet_version: 1,
    knowledge_sources: [{source_id: "SHEETS-FUNC-QUERY", title: "QUERY"}],
    cross_sheet_edges: [{consumer_sheet: "sheet_01", source_sheet: "sheet_02", formula_cells: 9}]
  };
  const result = {
    summary: "Five hypotheses, no verified speedup.",
    proposals: Array.from({length: 5}, (_, index) => ({
      title: "Proposal " + (index + 1),
      rationale: "Rationale " + (index + 1),
      risk: "high", impact: "unknown",
      target_sheets: ["sheet_01"],
      validation_steps: ["Compare cell output " + (index + 1)],
      source_ids: ["SHEETS-FUNC-QUERY"]
    })),
    missing_context: ["Need dates and null semantics."]
  };
  const ui = setup(async (url, opts) => {
    if (url === "/v1/ai/preview") {
      return {ok: true, json: async () => ({
        preview_hash: "synthetic-digest", packet, destination: "host.docker.internal",
        ready: true, model: "qwen3.5:4b"
      })};
    }
    if (url === "/v1/ai/suggest") {
      return {ok: true, json: async () => ({
        result, model: "qwen3.5:4b", provider: "local"
      })};
    }
    if (url === "/v1/reports/ai/pdf") {
      postedPDF = JSON.parse(opts.body);
      return {ok: true, blob: async () => new Blob(["%PDF-"], {type: "application/pdf"})};
    }
    throw Error("Unexpected network request: " + url);
  });
  await ui.find(x => x.tag === "button" &&
    x.textContent === "Visualizar pacote para IA").trigger();
  const consent = ui.find(x => x.tag === "input" && x.type === "checkbox" &&
    descendants(ui.root).some(p => p.classList.contains("ai-consent") &&
      descendants(p).includes(x)));
  consent.checked = true;
  await consent.trigger("change");
  await ui.find(x => x.tag === "button" && x.textContent === "Gerar propostas com IA").trigger();

  await ui.find(x => x.tag === "button" && x.textContent === "Exportar JSON completo").trigger();
  assert.equal(ui.downloads.length, 1);
  const file = JSON.parse(await ui.downloads[0].text());
  assert.equal(file.analysis.proposals.length, 5);
  assert.deepEqual(file.analysis.missing_context, result.missing_context);
  assert.equal(file.context_packet.cross_sheet_edges[0].formula_cells, 9);
  assert.equal(file.context_sha256, "synthetic-digest");
  assert.equal(file.model, "qwen3.5:4b");
  assert.equal(file.performance_measured, false);
  assert.equal(file.writes_performed, false);

  await ui.find(x => x.tag === "button" && x.textContent === "Exportar PDF completo").trigger();
  assert.equal(ui.downloads.length, 2);
  assert.equal(ui.downloads[1].type, "application/pdf");
  assert.equal(postedPDF.context_sha256, file.context_sha256);
  assert.equal(JSON.stringify(postedPDF.analysis), JSON.stringify(file.analysis));
  assert.equal(JSON.stringify(postedPDF.context_packet), JSON.stringify(file.context_packet));
});

test("formula evidence requires separate Google read and model opt-ins", async () => {
  const requests = [];
  const ui = setup(async (url, options) => {
    requests.push({url, body: JSON.parse(options.body)});
    if (url === "/v1/ai/formula-samples") {
      return {ok: true, json: async () => ({
        examples: [{a1: "C3", formula_template: '=SUMIFS(A:A;B:B;"<TEXT>")'}],
        sent_to_ai: false, writes_performed: false
      })};
    }
    if (url === "/v1/ai/preview") {
      return {ok: true, json: async () => ({
        preview_hash: "new-hash", packet: {knowledge_sources: []},
        ready: true, destination: "host.docker.internal", model: "qwen3.5:4b"
      })};
    }
    throw Error("Unexpected request: " + url);
  });
  const focus = ui.find(x => x.tag === "select" &&
    x.attributes["aria-label"] === "Aba para análise por IA");
  focus.value = "Overview";
  await focus.trigger("change");
  await ui.find(x => x.tag === "button" &&
    x.textContent === "Buscar amostras no Google (somente leitura)").trigger();
  assert.equal(requests[0].body.focus_sheet, "Overview");
  assert.equal(requests[0].body.read_consent, true);
  const include = ui.find(x => x.tag === "input" && x.type === "checkbox" &&
    descendants(ui.root).some(p => p.classList.contains("ai-sample-consent") &&
      descendants(p).includes(x)));
  assert.equal(include.disabled, false);
  assert.equal(include.checked, false);
  await ui.find(x => x.tag === "button" &&
    x.textContent === "Visualizar pacote para IA").trigger();
  assert.equal(requests[1].body.formula_samples.length, 0);
  include.checked = true;
  await include.trigger("change");
  await ui.find(x => x.tag === "button" &&
    x.textContent === "Visualizar pacote para IA").trigger();
  assert.equal(requests[2].body.formula_samples.length, 1);
  assert.equal(requests[2].body.formula_samples[0].a1, "C3");
});
