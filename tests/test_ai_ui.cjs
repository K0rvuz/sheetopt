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
}

function descendants(node) {
  const children = node?.children || [];
  return [node, ...children.flatMap(descendants)];
}

function setup(fetchImpl) {
  const root = new Element("div");
  const notice = new Element("div");
  const timers = new Map();
  let nextTimer = 0;
  const window = {
    setInterval: (callback) => {
      const id = ++nextTimer;
      timers.set(id, callback);
      return id;
    },
    clearInterval: (id) => timers.delete(id)
  };
  const document = {
    getElementById: (id) => id === "results" ? root : notice,
    createElement: (tag) => new Element(tag),
    createTextNode: (value) => new Element("text", String(value))
  };
  vm.runInNewContext(fs.readFileSync(path.join(WEB_DIR, "report.js"), "utf8"), {
    window, document, fetch: fetchImpl, URL, Blob, Date,
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
  return { find, root, timers };
}

test("AI UI shows scoped checkboxes and remains idle before approval", () => {
  const ui = setup(async () => { throw Error("Unexpected network call"); });
  const checkboxes = descendants(ui.root).filter(x => x.tag === "input" && x.type === "checkbox");
  assert.equal(checkboxes.length, 2);
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
