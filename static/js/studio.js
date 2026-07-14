/* Studio page: run the pipeline and browse generated artifacts. */

const STAGES = [
  ["seed", "Seed"],
  ["curator", "Curator"],
  ["designer", "Data Designer"],
  ["synthesizer", "Synthesizer"],
  ["latex_harness", "LaTeX Harness"],
  ["pdf", "PDF"],
];

function renderStages(state, reports = {}) {
  const box = document.getElementById("stages");
  box.innerHTML = "";
  for (const [key, label] of STAGES) {
    const stage = el("div", { class: "stage " + (state[key] || "") });
    stage.append(el("div", { class: "name", text: label }));
    const statusText = { done: "done", running: "running…" }[state[key]] || "idle";
    stage.append(el("div", { class: "status", text: statusText }));
    if (reports[key]) {
      const detail = Object.entries(reports[key])
        .filter(([k]) => !["example", "seed_stats"].includes(k))
        .map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v).slice(0, 60) : v}`)
        .join("\n");
      stage.append(el("div", { class: "stage-detail", text: detail }));
    }
    box.append(stage);
  }
}

function renderDocs(manifest) {
  const card = document.getElementById("results-card");
  card.style.display = "";
  document.getElementById("run-id-badge").textContent = manifest.run_id;
  document.getElementById("download-dataset").href = `/api/runs/${manifest.run_id}/dataset`;
  document.getElementById("schema-badge").textContent =
    `${manifest.schema.doc_type} · ${manifest.schema.locale || "en_US"}` +
    (manifest.llm_backed ? " · LLM-backed" : " · offline synth");
  const engines = [...new Set(manifest.docs.map((d) => d.pdf_engine))].join(", ");
  document.getElementById("engine-badge").textContent = `engine: ${engines}`;

  const box = document.getElementById("docs");
  box.innerHTML = "";
  for (const doc of manifest.docs) {
    const cardEl = el("div", { class: "doc-card" });
    if (doc.png_path) {
      cardEl.append(el("img", {
        class: "thumb",
        src: doc.png_path,
        alt: `Document ${doc.index}`,
        loading: "lazy",
        onclick: () => openViewer(manifest.run_id, doc.index, "png"),
      }));
    }
    const meta = el("div", { class: "meta" });
    meta.append(el("strong", { text: `doc_${doc.index}` }));
    meta.append(el("span", { class: "badge", text: manifest.schema.doc_type }));
    cardEl.append(meta);
    const links = el("div", { class: "links" });
    links.append(el("a", { href: "#", text: "JSON", onclick: (e) => { e.preventDefault(); openViewer(manifest.run_id, doc.index, "json"); } }));
    links.append(el("a", { href: "#", text: "LaTeX", onclick: (e) => { e.preventDefault(); openViewer(manifest.run_id, doc.index, "tex"); } }));
    links.append(el("a", { href: doc.pdf_path, text: "PDF ↓", download: "" }));
    cardEl.append(links);
    box.append(cardEl);
  }
}

async function loadRuns() {
  const box = document.getElementById("runs-list");
  try {
    const runs = await api("/api/runs");
    if (!runs.length) return;
    box.classList.remove("empty");
    box.innerHTML = "";
    const table = el("table");
    for (const run of runs.slice(0, 12)) {
      const tr = el("tr", {
        class: "clickable",
        onclick: async () => {
          const manifest = await api(`/api/runs/${run.run_id}`);
          const reports = Object.fromEntries(manifest.stages.map((s) => [s.stage, s.detail]));
          renderStages(Object.fromEntries(STAGES.map(([k]) => [k, "done"])), reports);
          renderDocs(manifest);
        },
      });
      tr.append(el("td", { text: run.run_id.slice(0, 14) }));
      tr.append(el("td", { text: run.doc_type || "?" }));
      tr.append(el("td", { class: "num", text: `${run.num_docs} docs` }));
      table.append(tr);
    }
    box.append(table);
  } catch (_) { /* leave empty state */ }
}

document.querySelectorAll('input[name="source"]').forEach((radio) => {
  radio.addEventListener("change", () => {
    document.getElementById("hf-fields").style.display =
      document.querySelector('input[name="source"]:checked').value === "huggingface" ? "" : "none";
  });
});

document.getElementById("hf-preview-btn").addEventListener("click", async () => {
  const out = document.getElementById("hf-preview");
  const ds = document.getElementById("hf-dataset").value.trim();
  if (!ds) { out.textContent = "Enter a dataset name first."; return; }
  out.textContent = "Loading…";
  try {
    const preview = await api(`/api/hf/preview?dataset=${encodeURIComponent(ds)}&limit=3`);
    out.textContent = JSON.stringify(preview.rows, null, 2);
  } catch (err) {
    out.textContent = "Error: " + err.message;
  }
});

document.getElementById("run-btn").addEventListener("click", async () => {
  const btn = document.getElementById("run-btn");
  const errBox = document.getElementById("run-error");
  errBox.innerHTML = "";
  const prompt = document.getElementById("prompt").value.trim();
  if (prompt.length < 3) {
    errBox.append(el("div", { class: "error-box", text: "Please enter a prompt (at least a few words)." }));
    return;
  }
  const body = {
    source_type: document.querySelector('input[name="source"]:checked').value,
    hf_dataset: document.getElementById("hf-dataset").value.trim() || null,
    prompt,
    num_docs: parseInt(document.getElementById("num-docs").value, 10) || 5,
    doc_type: document.getElementById("doc-type").value || null,
  };

  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>Running pipeline…';
  // The API is a single call; animate stages optimistically while it runs.
  const order = STAGES.map(([k]) => k);
  let step = 0;
  renderStages({ [order[0]]: "running" });
  const ticker = setInterval(() => {
    step = Math.min(step + 1, order.length - 1);
    const state = {};
    order.forEach((k, i) => { state[k] = i < step ? "done" : i === step ? "running" : ""; });
    renderStages(state);
  }, 900);

  try {
    const manifest = await api("/api/pipeline/run", { method: "POST", body: JSON.stringify(body) });
    clearInterval(ticker);
    const reports = Object.fromEntries(manifest.stages.map((s) => [s.stage, s.detail]));
    renderStages(Object.fromEntries(order.map((k) => [k, "done"])), reports);
    renderDocs(manifest);
    loadRuns();
  } catch (err) {
    clearInterval(ticker);
    renderStages({});
    errBox.append(el("div", { class: "error-box", text: "Pipeline failed: " + err.message }));
  } finally {
    btn.disabled = false;
    btn.textContent = "Run pipeline";
  }
});

renderStages({});
loadRuns();
