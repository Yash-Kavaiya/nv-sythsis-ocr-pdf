/* Eval Lab: score a user-supplied OCR model against generated ground truth. */

let currentRunId = null;

async function loadRunOptions() {
  const select = document.getElementById("run-select");
  select.innerHTML = "";
  const runs = await api("/api/runs");
  if (!runs.length) {
    select.append(el("option", { text: "No runs available - generate documents first", value: "" }));
    return;
  }
  for (const run of runs) {
    select.append(el("option", {
      value: run.run_id,
      text: `${run.run_id.slice(0, 14)} · ${run.doc_type || "?"} · ${run.num_docs} docs · ${(run.prompt || "").slice(0, 40)}`,
    }));
  }
}

/* ---- stat tiles ---- */
const TILE_DEFS = [
  ["field_accuracy", "Field accuracy", "exact matches / fields", true],
  ["fuzzy_field_accuracy", "Fuzzy accuracy", "mean per-field similarity", true],
  ["cer", "CER", "character error rate (lower is better)", false],
  ["wer", "WER", "word error rate (lower is better)", false],
  ["structure_f1", "Structure F1", "JSON key-tree overlap", true],
];

function renderTiles(agg) {
  const box = document.getElementById("tiles");
  box.innerHTML = "";
  for (const [key, label, sub] of TILE_DEFS) {
    const tile = el("div", { class: "tile" });
    tile.append(el("div", { class: "label", text: label }));
    tile.append(el("div", { class: "value", text: agg[key] != null ? fmtPct(agg[key]) : "–" }));
    tile.append(el("div", { class: "sub", text: sub }));
    box.append(tile);
  }
}

/* ---- single-series bar chart (SVG, hover tooltip, no per-bar labels) ---- */
function renderChart(docs) {
  const box = document.getElementById("chart");
  box.innerHTML = "";
  const scored = docs.filter((d) => !d.error);
  if (!scored.length) {
    box.append(el("div", { class: "empty", text: "No successfully scored documents." }));
    return;
  }
  const W = 720, H = 240, mL = 44, mR = 12, mT = 10, mB = 28;
  const plotW = W - mL - mR, plotH = H - mT - mB;
  const n = docs.length;
  const step = plotW / n;
  const barW = Math.max(6, Math.min(40, step * 0.6));
  const svgNS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(svgNS, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "Exact field accuracy per document");

  const make = (tag, attrs) => {
    const node = document.createElementNS(svgNS, tag);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
    return node;
  };

  // gridlines + y labels at 0/25/50/75/100%
  for (let i = 0; i <= 4; i++) {
    const v = i / 4;
    const y = mT + plotH * (1 - v);
    svg.append(make("line", {
      x1: mL, x2: W - mR, y1: y, y2: y,
      stroke: i === 0 ? "var(--baseline)" : "var(--grid)", "stroke-width": 1,
    }));
    const label = make("text", {
      x: mL - 8, y: y + 4, "text-anchor": "end",
      fill: "var(--text-muted)", "font-size": 11,
    });
    label.textContent = `${v * 100}%`;
    svg.append(label);
  }

  const tooltip = el("div", { class: "tooltip" });
  for (const doc of docs) {
    const v = doc.error ? 0 : doc.field_accuracy;
    const x = mL + step * doc.index + (step - barW) / 2;
    const h = Math.max(v > 0 ? 4 : 0, plotH * v);
    const y = mT + plotH - h;
    const r = Math.min(4, barW / 2, h);
    // rounded data-end (top), flat at the baseline
    const path = h > 0
      ? `M${x},${y + h} L${x},${y + r} Q${x},${y} ${x + r},${y} L${x + barW - r},${y} Q${x + barW},${y} ${x + barW},${y + r} L${x + barW},${y + h} Z`
      : "";
    if (path) svg.append(make("path", { d: path, fill: doc.error ? "var(--baseline)" : "var(--series-1)" }));

    const xLabel = make("text", {
      x: x + barW / 2, y: H - 8, "text-anchor": "middle",
      fill: "var(--text-muted)", "font-size": 11,
    });
    xLabel.textContent = `doc ${doc.index}`;
    svg.append(xLabel);

    // hover hit target spans the full column, larger than the mark
    const hit = make("rect", {
      x: mL + step * doc.index, y: mT, width: step, height: plotH, fill: "transparent",
    });
    hit.addEventListener("mousemove", (evt) => {
      const rect = box.getBoundingClientRect();
      // Build via DOM nodes (textContent) — doc.error is untrusted (model/endpoint text).
      tooltip.textContent = "";
      const line1 = el("div", {}, [
        el("span", { class: "k", text: `doc ${doc.index} ` }),
        doc.error
          ? el("span", { class: "v", text: "failed" })
          : el("span", { class: "v", text: fmtPct(doc.field_accuracy) }),
      ]);
      const line2 = doc.error
        ? el("span", { class: "k", text: String(doc.error).slice(0, 60) })
        : el("span", { class: "k", text: `fuzzy ${fmtPct(doc.fuzzy_field_accuracy)} · CER ${fmtPct(doc.cer)}` });
      tooltip.append(line1, line2);
      tooltip.style.left = Math.min(evt.clientX - rect.left + 12, rect.width - 180) + "px";
      tooltip.style.top = (evt.clientY - rect.top - 40) + "px";
      tooltip.classList.add("show");
    });
    hit.addEventListener("mouseleave", () => tooltip.classList.remove("show"));
    hit.addEventListener("click", () => currentRunId && openViewer(currentRunId, doc.index, "png"));
    svg.append(hit);
  }
  box.append(svg, tooltip);
}

/* ---- per-doc table with expandable field diffs (the table view) ---- */
function renderDocTable(docs) {
  const box = document.getElementById("doc-table");
  box.innerHTML = "";
  const table = el("table");
  const head = el("tr");
  for (const h of ["Doc", "Fields", "Exact", "Fuzzy", "CER", "WER", "Struct F1", ""]) {
    head.append(el("th", { text: h, class: ["Doc", ""].includes(h) ? "" : "num" }));
  }
  table.append(head);
  for (const doc of docs) {
    const tr = el("tr");
    tr.append(el("td", { text: `doc_${doc.index}` }));
    if (doc.error) {
      const td = el("td", { text: `error: ${doc.error}`, class: "match-miss" });
      td.colSpan = 6;
      tr.append(td);
      table.append(tr);
      continue;
    }
    tr.append(el("td", { class: "num", text: `${doc.matched_fields}/${doc.total_fields}` }));
    tr.append(el("td", { class: "num", text: fmtPct(doc.field_accuracy) }));
    tr.append(el("td", { class: "num", text: fmtPct(doc.fuzzy_field_accuracy) }));
    tr.append(el("td", { class: "num", text: fmtPct(doc.cer) }));
    tr.append(el("td", { class: "num", text: fmtPct(doc.wer) }));
    tr.append(el("td", { class: "num", text: fmtPct(doc.structure_f1) }));

    const details = el("details", { class: "fields" });
    details.append(el("summary", { text: "fields" }));
    const inner = el("table");
    const ih = el("tr");
    for (const h of ["Field", "Expected", "Predicted", "Match"]) ih.append(el("th", { text: h }));
    inner.append(ih);
    for (const f of doc.fields) {
      const row = el("tr");
      row.append(el("td", { text: f.field }));
      row.append(el("td", { text: String(f.expected ?? "") }));
      row.append(el("td", { text: String(f.predicted ?? "∅") }));
      row.append(el("td", { text: f.match, class: `match-${f.match}` }));
      inner.append(row);
    }
    details.append(inner);
    const td = el("td");
    td.append(details);
    tr.append(td);
    table.append(tr);
  }
  box.append(table);
}

function renderDashboard(result) {
  currentRunId = result.run_id;
  document.getElementById("dash").style.display = "";
  document.getElementById("dash-empty").style.display = "none";
  document.getElementById("eval-id-badge").textContent =
    `${result.eval_id} · ${result.model_name || result.mode}`;
  renderTiles(result.aggregate || {});
  renderChart(result.docs || []);
  renderDocTable(result.docs || []);
}

async function loadEvals() {
  const box = document.getElementById("evals-list");
  try {
    const evals = await api("/api/evals");
    if (!evals.length) return;
    box.classList.remove("empty");
    box.innerHTML = "";
    const table = el("table");
    for (const entry of evals.slice(0, 12)) {
      const tr = el("tr", {
        class: "clickable",
        onclick: async () => renderDashboard(await api(`/api/evals/${entry.eval_id}`)),
      });
      tr.append(el("td", { text: entry.eval_id.slice(0, 15) }));
      tr.append(el("td", { text: entry.model_name || entry.mode }));
      tr.append(el("td", {
        class: "num",
        text: entry.aggregate?.field_accuracy != null ? fmtPct(entry.aggregate.field_accuracy) : "–",
      }));
      table.append(tr);
    }
    box.append(table);
  } catch (_) { /* leave empty state */ }
}

document.querySelectorAll('input[name="mode"]').forEach((radio) => {
  radio.addEventListener("change", () => {
    const mode = document.querySelector('input[name="mode"]:checked').value;
    document.getElementById("model-fields").style.display = mode === "model" ? "" : "none";
    document.getElementById("upload-fields").style.display = mode === "upload" ? "" : "none";
  });
});

document.getElementById("eval-btn").addEventListener("click", async () => {
  const btn = document.getElementById("eval-btn");
  const errBox = document.getElementById("eval-error");
  errBox.innerHTML = "";
  const runId = document.getElementById("run-select").value;
  if (!runId) {
    errBox.append(el("div", { class: "error-box", text: "No dataset run selected." }));
    return;
  }
  const mode = document.querySelector('input[name="mode"]:checked').value;
  const body = { run_id: runId, mode };
  if (mode === "model") {
    const baseUrl = document.getElementById("base-url").value.trim();
    const model = document.getElementById("model-name").value.trim();
    if (!baseUrl || !model) {
      errBox.append(el("div", { class: "error-box", text: "Base URL and model name are required." }));
      return;
    }
    body.model_config = {
      base_url: baseUrl,
      api_key: document.getElementById("api-key").value.trim(),
      model,
    };
  } else {
    try {
      body.predictions = JSON.parse(document.getElementById("predictions").value);
    } catch (err) {
      errBox.append(el("div", { class: "error-box", text: "Predictions must be valid JSON: " + err.message }));
      return;
    }
  }

  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>Evaluating…';
  try {
    const result = await api("/api/eval/run", { method: "POST", body: JSON.stringify(body) });
    renderDashboard(result);
    loadEvals();
  } catch (err) {
    errBox.append(el("div", { class: "error-box", text: "Evaluation failed: " + err.message }));
  } finally {
    btn.disabled = false;
    btn.textContent = "Run evaluation";
  }
});

loadRunOptions();
loadEvals();
