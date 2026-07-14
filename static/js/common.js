/* Shared helpers: API wrapper, health badge, artifact viewer, theme toggle. */

function initThemeToggle() {
  const btn = document.getElementById("theme-toggle-btn");
  if (!btn) return;
  btn.addEventListener("click", () => {
    const current = document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
    const next = current === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem("theme", next); } catch (e) {}
  });
}
initThemeToggle();

async function api(path, options = {}) {
  const resp = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!resp.ok) {
    let detail = resp.statusText;
    try { detail = (await resp.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return resp.json();
}

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (k === "text") node.textContent = v;
    else node.setAttribute(k, v);
  }
  for (const child of [].concat(children)) {
    if (child != null) node.append(child);
  }
  return node;
}

function fmtPct(x) {
  return (x * 100).toFixed(1) + "%";
}

async function loadHealth() {
  try {
    const h = await api("/api/health");
    const dot = document.getElementById("llm-dot");
    const label = document.getElementById("llm-label");
    if (dot && label) {
      dot.classList.toggle("on", h.llm_available);
      label.textContent = h.llm_available ? `LLM: ${h.llm_model}` : "LLM: offline fallback";
    }
    const pdf = document.getElementById("pdf-label");
    if (pdf) pdf.textContent = `PDF: ${h.latex_engine}`;
  } catch (_) { /* header badge only */ }
}

/* ---- artifact viewer (used by both pages) ---- */
function openViewer(runId, index, initialTab = "png") {
  const dialog = document.getElementById("viewer");
  if (!dialog) return;
  document.getElementById("viewer-title").textContent = `Document ${index}`;
  const tabs = [
    ["png", "Preview"],
    ["pdf", "PDF"],
    ["tex", "LaTeX"],
    ["json", "JSON"],
  ];
  const tabsBox = document.getElementById("viewer-tabs");
  tabsBox.innerHTML = "";
  const body = document.getElementById("viewer-body");

  async function show(kind) {
    tabsBox.querySelectorAll("button").forEach((b) =>
      b.classList.toggle("active", b.dataset.kind === kind));
    body.innerHTML = "";
    const url = `/api/runs/${runId}/docs/${index}/${kind}`;
    if (kind === "png") {
      body.append(el("img", { src: url, alt: `Document ${index} preview` }));
    } else if (kind === "pdf") {
      body.append(el("iframe", { src: url, title: `Document ${index} PDF` }));
    } else {
      const resp = await fetch(url);
      const text = await resp.text();
      const pretty = kind === "json" ? JSON.stringify(JSON.parse(text), null, 2) : text;
      body.append(el("pre", { text: pretty }));
    }
  }

  for (const [kind, label] of tabs) {
    tabsBox.append(el("button", { text: label, "data-kind": kind, onclick: () => show(kind) }));
  }
  show(initialTab);
  dialog.showModal();
}

loadHealth();
