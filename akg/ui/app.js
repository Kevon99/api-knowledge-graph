const API = "/api/v1";

// monitor de inicializacion
setTimeout(() => {
  if (typeof renderGraph === 'function') console.log("[AKG] renderGraph OK");
  else console.error("[AKG] renderGraph UNDEFINED");
  if (typeof wireBlocklist === 'function') console.log("[AKG] wireBlocklist OK");
}, 100);

const $ = (sel) => document.querySelector(sel);
const graphEl = $("#graph");
const logEl = $("#log");

function log(msg, cls = "") {
  const div = document.createElement("div");
  div.className = "line " + cls;
  div.textContent = msg;
  logEl.prepend(div);
}

async function api(path, opts = {}) {
  const res = await fetch(API + path, opts);
  const body = await res.json().catch(() => null);
  return { ok: res.ok, status: res.status, body };
}

// ── Resumen ────────────────────────────────────────────────────────────
async function loadSummary() {
  const ws = $("#ws-select").value;
  const path = ws ? `/graph/summary?workspace_id=${encodeURIComponent(ws)}` : "/graph/summary";
  const { ok, body } = await api(path);
  if (!ok) { $("#summary").textContent = "sin datos"; return; }
  const nodes = body.node_counts || {};
  const rels = body.relationship_counts || {};
  const rows = Object.entries(nodes)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8)
    .map(([k, v]) => `<div class="row"><span>${k}</span><span class="count">${v}</span></div>`)
    .join("");
  $("#summary").innerHTML = rows || "<div class='row'>vacío</div>";
  window.__rels = rels;
}

// ---- Workspaces ────────────────────────────────────────────────────────
function resetGraphView() {
  $("#summary").innerHTML = "<div class='row'>sin workspaces</div>";
  if (cy) { cy.destroy(); cy = null; }
  graphEl.innerHTML = "<div class='hint'>crea o selecciona un workspace</div>";
  lastGraph = null;
  nodesById.clear();
  originalGraphData = null;
  isolatedNodeId = null;
  closeDetail();
}

async function loadWorkspaces() {
  const { ok, body } = await api("/workspaces");
  if (!ok) return;
  const sel = $("#ws-select");
  if (!body.items || !body.items.length) {
    sel.innerHTML = "";
    sel.dataset.name = "default";
    resetGraphView();
    return;
  }
  sel.innerHTML = body.items
    .map((w) => `<option value="${w.id}">${w.name}</option>`)
    .join("");
  sel.dataset.name = body.items[0]?.name || "default";
  await loadSummary();
  runQuery();
}

async function createWorkspace() {
  const name = prompt("Nombre del workspace:");
  if (!name) return;
  const { ok } = await api("/workspaces", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  log(ok ? `workspace "${name}" creado` : "error al crear", ok ? "ok" : "err");
  await loadWorkspaces();
}

async function deleteWorkspace() {
  const ws = $("#ws-select");
  const id = ws.value;
  const name = ws.options[ws.selectedIndex]?.text || id;
  if (!id) {
    log("no hay workspace para eliminar", "err");
    return;
  }
  if (!confirm(`¿Eliminar el workspace "${name}" y todo su contenido?`)) return;
  const { ok, status, body } = await api(
    `/workspaces/${encodeURIComponent(id)}`,
    { method: "DELETE" }
  );
  if (!ok) {
    const msg = body?.error?.message || body?.detail || status;
    log(`error al eliminar: ${msg}`, "err");
    return;
  }
  log(`workspace "${name}" eliminado`, "ok");
  await loadWorkspaces();
}

// ── Importar ────────────────────────────────────────────────────────────
function detectFormat(fileName) {
  const ext = (fileName.split(".").pop() || "").toLowerCase();
  if (ext === "xml" || ext === "txt") return "burp_xml";
  return "burp_json";
}

async function uploadFile(file) {
  const ws = $("#ws-select").value;
  if (!ws) {
    log("crea o selecciona un workspace primero", "err");
    return;
  }
  const format = detectFormat(file.name);
  const fd = new FormData();
  fd.append("file", file);
  log(`subiendo ${file.name} (${format}) …`, "");
  const res = await fetch(`${API}/imports?workspace_id=${ws}&source_format=${format}`, {
    method: "POST",
    body: fd,
  });
  const body = await res.json().catch(() => ({}));
  if (res.ok) {
    log(`pipeline ${body.status} · ${body.parsed} exchanges · ${body.parse_errors} errores`, "ok");
  } else {
    log(`import fallido: ${body.detail || body.error || res.status}`, "err");
  }
  await loadSummary();
  runQuery();
}

// ── Grafo (consulta Cypher → cytoscape + dagre) ─────────────────────────
if (window.cytoscape && window.cytoscapeDagre) cytoscape.use(window.cytoscapeDagre);
let cy = null;

// Paleta de categoría (apagada; el color "fuerte" se reserva a estado/datos)
const NODE_COLORS = {
  Host: { bg: "#8ea3b8", border: "#5b6b7c" },
  Endpoint: { bg: "#3fb950", border: "#238636" },
  Token: { bg: "#f85149", border: "#b62324" },
  Cookie: { bg: "#d2a8ff", border: "#8957e5" },
  Session: { bg: "#d29922", border: "#9e6a03" },
  Resource: { bg: "#39c5cf", border: "#1b7c83" },
  Flow: { bg: "#f0883e", border: "#bc4c00" },
  AuthFlow: { bg: "#f0883e", border: "#bc4c00" },
  Exchange: { bg: "#6e7681", border: "#484f58" },
  Header: { bg: "#db61a2", border: "#a93d79" },
};

const DEFAULT_BG = "#8b949e";
const BORDER_SOFT = "#30363d";
const ACCENT = "#58a6ff";
const LABEL_COLOR = "#8b949e";

// Color de arista = confianza de la relación
const CONF_COLORS = { EVIDENCIA: "#3fb950", INFERENCIA: "#d29922", HIPOTESIS: "#f85149" };

const NODE_SHAPES = {
  Host: "hexagon",
  Endpoint: "ellipse",
  Token: "diamond",
  Cookie: "triangle",
  Session: "rectangle",
  Resource: "round-rectangle",
  Flow: "tag",
  AuthFlow: "star",
  Exchange: "ellipse",
  Header: "barrel",
};

// Señal auth → anillo (borde) en elendpoint, no cambia el relleno
const AUTH_RING = {
  token: "#79c0ff",
  cookie: "#d2a8ff",
};

// ── Ajustes de layout (persistidos en localStorage) ─────────────────────
// ── Ajustes de layout dagre (persistidos en localStorage) ─────────────
// spring → separación entre nodos del mismo nivel · repulsion → separación entre niveles
const LAYOUT_PRESETS = {
  dense: { spring: 10, repulsion: 40, overlap: 0.0, size: 8, font: 8 },
  compact: { spring: 16, repulsion: 56, overlap: 0.0, size: 12, font: 9 },
  balanced: { spring: 28, repulsion: 88, overlap: 0.0, size: 16, font: 10 },
  expanded: { spring: 48, repulsion: 140, overlap: 0.0, size: 22, font: 12 },
};
const ACTIVE_PRESET = "balanced";

let activePreset = ACTIVE_PRESET;
let layout = { ...LAYOUT_PRESETS.balanced };
try {
  const saved = JSON.parse(localStorage.getItem("akg-layout2"));
  if (saved?.preset && LAYOUT_PRESETS[saved.preset]) {
    activePreset = saved.preset;
    layout = { ...LAYOUT_PRESETS[activePreset] };
  }
} catch (_) {}

function saveLayout() {
  const preset = LAYOUT_PRESETS[activePreset] ? activePreset : "balanced";
  try { localStorage.setItem("akg-layout2", JSON.stringify({ preset })); } catch (_) {}
}

let NODE_TYPES_VISIBLE = {
  Host: true, Endpoint: true, Token: true, Cookie: true,
  Session: true, Resource: true, Flow: true, AuthFlow: true, Exchange: false,
  Header: true,
};

function applyNodeTypeFilter() {
  try { localStorage.setItem("akg-nodetypes", JSON.stringify(NODE_TYPES_VISIBLE)); } catch (_) {}
  rerenderLayout();
}

try {
  const saved = JSON.parse(localStorage.getItem("akg-nodetypes"));
  if (saved) NODE_TYPES_VISIBLE = { ...NODE_TYPES_VISIBLE, ...saved };
} catch (_) {}

// ── Lista de excluidos ──
// Entradas: { type: "host"|"endpoint", value: String }
let BLOCKLIST = [];
try {
  const saved = JSON.parse(localStorage.getItem("akg-blocklist-v2") || "[]");
  if (Array.isArray(saved)) {
    BLOCKLIST = saved
      .map((e) => {
        if (typeof e === "string") {
          const isEp = /^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS) /i.test(e);
          return { type: isEp ? "endpoint" : "host", value: e.trim() };
        }
        return e.type && ["host","endpoint"].includes(e.type) ? { type: e.type, value: (e.value||"").trim() } : null;
      })
      .filter(Boolean);
  }
} catch (_) { BLOCKLIST = []; }

function persistBlocklist() {
  try { localStorage.setItem("akg-blocklist-v2", JSON.stringify(BLOCKLIST)); } catch (_) {}
}

function blockHosts() { return BLOCKLIST.filter((b) => b.type === "host").map((b) => b.value); }
function blockEndpoints() { return BLOCKLIST.filter((b) => b.type === "endpoint").map((b) => b.value); }

function isBlockedNode(nd) {
  if (!BLOCKLIST.length) return false;
  const props = nd.props || nd.properties || nd || {};
  const host = (props.host || props.name || "").toLowerCase().replace(/^https?:\/\//, "").replace(/\/$/, "");
  const pattern = (props.pattern || props.path || "").toLowerCase();
  const method = (props.method || "").toLowerCase();

  for (const b of BLOCKLIST) {
    const val = b.value.toLowerCase();
    if (b.type === "host" && host && host.includes(val)) return true;
    if (b.type === "endpoint" && method && pattern) {
      if (val.includes(method) && val.includes(pattern)) return true;
      if (pattern.includes(val.replace(/^(get|post|put|patch|delete|head|options)\s+/i, ""))) return true;
    }
  }
  return false;
}

function classifyBlockTerm(term) {
  const t = term.trim();
  if (!t) return null;
  if (/^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS) /i.test(t)) return "endpoint";
  if (t.includes("/") || /^https?:\/\//i.test(t)) return "endpoint";
  if (/^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/.test(t)) return "host";
  return "host";
}

function addBlock(term) {
  const t = term.trim();
  if (!t) return;
  const type = classifyBlockTerm(t);
  const exists = BLOCKLIST.some((b) => b.type === type && b.value.toLowerCase() === t.toLowerCase());
  if (!exists) {
    BLOCKLIST.push({ type, value: t });
    persistBlocklist();
    renderBlockList();
    rerenderLayout();
  }
}

function removeBlock(entry) {
  BLOCKLIST = BLOCKLIST.filter((b) =>
    !(b.type === entry.type && b.value.toLowerCase() === entry.value.toLowerCase())
  );
  persistBlocklist();
  renderBlockList();
  rerenderLayout();
}

function renderBlockList() {
  const el = document.getElementById("block-list");
  if (!el) return;
  const hosts = blockHosts();
  const eps = blockEndpoints();

  const lines = [];
  hosts.forEach((h) => {
    lines.push('<div class="block-item b-host" data-type="host" data-val="' + escapeHtml(h) + '">' +
      '<span class="bi-badge" style="background:#4c72b0;border:1px solid #2a4a8a;color:#fff;font-size:9px;padding:0 4px;border-radius:3px;margin-right:5px;">H</span>' +
      '<span class="bi-label" title="' + escapeHtml(h) + '">' + escapeHtml(h) + '</span>' +
      '<button class="bi-x" data-type="host" data-val="' + escapeHtml(h) + '">\u2715</button></div>');
  });
  eps.forEach((ep) => {
    lines.push('<div class="block-item b-ep" data-type="endpoint" data-val="' + escapeHtml(ep) + '">' +
      '<span class="bi-badge" style="background:#55a868;border:1px solid #33703d;color:#fff;font-size:9px;padding:0 4px;border-radius:3px;margin-right:5px;">EP</span>' +
      '<span class="bi-label" title="' + escapeHtml(ep) + '">' + escapeHtml(ep) + '</span>' +
      '<button class="bi-x" data-type="endpoint" data-val="' + escapeHtml(ep) + '">\u2715</button></div>');
  });
  const cth = document.getElementById("bt-count-host"), cte = document.getElementById("bt-count-ep");
  if (cth) cth.textContent = hosts.length;
  if (cte) cte.textContent = eps.length;
  el.innerHTML = lines.length ? lines.join("") : '<div class="block-item"><span class="bi-label muted">sin exclusiones</span></div>';
}

function renderBlockPickList() {
  const pl = document.getElementById("block-pick-list");
  if (!pl || !lastGraph) return;
  const allNodes = lastGraph.allNodes || [];
  const seenHosts = new Set();
  const seenEndpoints = new Map();

  allNodes.forEach((n) => {
    const props = n.props || n._props || n || {};
    const host = (props.host || props.name || "").replace(/^https?:\/\//, "").replace(/\/$/, "").trim();
    const pattern = (props.pattern || props.path || "").trim();
    const method = (props.method || "").trim();
    if (host) seenHosts.add(host);
    if (method && pattern) {
      const key = method + " " + pattern;
      if (!seenEndpoints.has(key)) seenEndpoints.set(key, host);
    }
  });

  const blockedHosts = new Set(blockHosts().map((v) => v.toLowerCase()));
  const blockedEps = new Set(blockEndpoints().map((v) => v.toLowerCase()));

  let items = "";

  Array.from(seenHosts).sort().forEach((h) => {
    const blocked = blockedHosts.has(h.toLowerCase());
    items += '<button class="bp-item' + (blocked ? ' bp-blocked' : '') + '" data-type="host" data-val="' + escapeHtml(h) + '">' +
      '<span class="bp-badge" style="background:#4c72b0;color:#fff;font-size:9px;padding:0 3px;border-radius:2px;">H</span> ' +
      escapeHtml(h) + (blocked ? ' (re-incluir)' : '') + '</button>';
  });

  Array.from(seenEndpoints.entries()).sort((a, b) => a[0].localeCompare(b[0])).forEach(([epKey, epHost]) => {
    const val = epKey + (epHost ? " @" + epHost : "");
    const blocked = blockedEps.has(val.toLowerCase());
    items += '<div class="bp-item' + (blocked ? ' bp-blocked' : '') + '" data-type="endpoint" data-val="' + escapeHtml(val) + '">' +
      '<span class="bp-badge" style="background:#55a868;color:#fff;font-size:9px;padding:0 3px;border-radius:2px;">EP</span> ' +
      escapeHtml(val) + (blocked ? ' (re-incluir)' : '') + '</div>';
  });

  pl.innerHTML = items || '<div class="bp-empty">No hay hosts o endpoints en el grafo actual.</div>';
}

function wireBlocklist() {
  renderBlockList();
  document.getElementById("btn-block-add").addEventListener("click", () => {
    const inp = document.getElementById("block-input");
    addBlock(inp.value);
    inp.value = "";
  });
  document.getElementById("block-input").addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    addBlock(e.target.value);
    e.target.value = "";
  });
  document.getElementById("block-list").addEventListener("click", (e) => {
    const x = e.target.closest(".bi-x");
    if (x) removeBlock({ type: x.dataset.type, value: x.dataset.val });
  });

  document.getElementById("block-pick-list").addEventListener("click", (e) => {
    const btn = e.target.closest(".bp-item");
    if (!btn) return;
    const val = btn.dataset.val;
    const btype = btn.dataset.type;
    const exists = BLOCKLIST.some((b) => b.type === btype && b.value.toLowerCase() === val.toLowerCase());
    if (exists) {
      removeBlock({ type: btype, value: val });
    } else {
      addBlock(val);
    }
    renderBlockPickList();
  });

  let t = null;
  document.getElementById("block-input").addEventListener("input", () => {
    clearTimeout(t);
    t = setTimeout(async () => {
      const q = (document.getElementById("block-input").value || "").trim();
      const dl = document.getElementById("block-suggest");
      if (!q || !dl) { if (dl) dl.innerHTML = ""; return; }
      const { ok, body } = await api("/graph/suggestions?q=" + encodeURIComponent(q) + "&limit=10");
      if (!ok || !body?.suggestions) return;
      dl.innerHTML = body.suggestions
        .map((s) => '<option value="' + escapeHtml(s) + '"></option>').join("");
    }, 220);
  });
}

// ── Headers rastreados ──────────────────────────────────────────────────
// La lista autoritativa vive en el servidor (por workspace); el localStorage
// solo es un cache para arrancar mas rapido.
let TRACKED_HEADERS = [];
try {
  const saved = JSON.parse(localStorage.getItem("akg-tracked-headers-v1") || "[]");
  if (Array.isArray(saved)) {
    TRACKED_HEADERS = saved
      .filter((h) => typeof h === "string" && h.trim())
      .map((h) => h.trim());
  }
} catch (_) { TRACKED_HEADERS = []; }

function persistTrackedHeaders() {
  try { localStorage.setItem("akg-tracked-headers-v1", JSON.stringify(TRACKED_HEADERS)); } catch (_) {}
}

function renderTrackedHeaderList() {
  const el = document.getElementById("header-list");
  if (!el) return;
  el.innerHTML = TRACKED_HEADERS.length
    ? TRACKED_HEADERS.map((h) =>
        '<div class="block-item">' +
          '<span class="bi-badge" style="background:#e84393;border:1px solid #a02963;color:#fff;font-size:9px;padding:0 4px;border-radius:3px;margin-right:5px;">H</span>' +
          '<span class="bi-label" title="' + escapeHtml(h) + '">' + escapeHtml(h) + '</span>' +
          '<button class="bi-x" data-header="' + escapeHtml(h) + '">\u2715</button></div>'
      ).join("")
    : '<div class="block-item"><span class="bi-label muted">sin headers rastreados</span></div>';
}

async function loadHeaderSuggestions() {
  const dl = document.getElementById("header-suggest");
  if (!dl) return;
  const q = (document.getElementById("header-input").value || "").trim();
  const ws = $("#ws-select").value;
  if (!q || !ws) { dl.innerHTML = ""; return; }
  const { ok, body } = await api(
    "/graph/header-suggestions?q=" + encodeURIComponent(q) +
    "&limit=10&workspace_id=" + encodeURIComponent(ws)
  );
  if (!ok || !body?.suggestions) return;
  dl.innerHTML = body.suggestions
    .map((s) => '<option value="' + escapeHtml(s) + '"></option>').join("");
}

// sincroniza la lista desde el servidor (fuente de verdad)
async function syncTrackedHeaders(showGraph) {
  const ws = $("#ws-select").value;
  if (!ws) { TRACKED_HEADERS = []; persistTrackedHeaders(); renderTrackedHeaderList(); return; }
  const { ok, body } = await api("/graph/headers?workspace_id=" + encodeURIComponent(ws));
  if (!ok || !Array.isArray(body?.tracked)) return;
  TRACKED_HEADERS = body.tracked;
  persistTrackedHeaders();
  renderTrackedHeaderList();
  if (showGraph) {
    if (TRACKED_HEADERS.length) buildGraphFromViews(body, "headers");
    else await runQuery();
  }
}

async function renderTrackedHeaders() {
  const ws = $("#ws-select").value;
  if (!ws) { log("selecciona un workspace primero", "err"); return; }
  if (!TRACKED_HEADERS.length) { await runQuery(); return; }
  const { ok, body } = await api("/graph/headers/track", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ headers: TRACKED_HEADERS, workspace_id: ws }),
  });
  if (!ok) {
    log("error al rastrear headers: " + (body?.error?.message || body?.detail || "desconocido"), "err");
    return;
  }
  if (body.tracked) { TRACKED_HEADERS = body.tracked; persistTrackedHeaders(); renderTrackedHeaderList(); }
  const headerNodes = (body.nodes || []).filter((n) => (n.labels || [])[0] === "Header");
  if (!headerNodes.length) {
    log("ninguno de estos headers aparece en este workspace", "err");
  }
  buildGraphFromViews(body, "headers");
  highlightAuthEndpoints(body.nodes);
  log("headers rastreados: " + TRACKED_HEADERS.join(", "), "ok");
}

async function addTrackedHeader() {
  const inp = document.getElementById("header-input");
  const name = (inp.value || "").trim();
  const ws = $("#ws-select").value;
  if (!name) return;
  if (!ws) { log("selecciona un workspace primero", "err"); return; }
  inp.value = "";
  document.getElementById("header-suggest").innerHTML = "";
  const { ok, body } = await api("/graph/headers/track", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ headers: [name], workspace_id: ws }),
  });
  if (!ok) {
    log("error al rastrear header: " + (body?.error?.message || body?.detail || "desconocido"), "err");
    return;
  }
  TRACKED_HEADERS = body.tracked || TRACKED_HEADERS;
  persistTrackedHeaders();
  renderTrackedHeaderList();
  const headerNodes = (body.nodes || []).filter((n) => (n.labels || [])[0] === "Header");
  if (!headerNodes.length) {
    log("el header '" + name + "' no aparece en este workspace", "err");
  }
  buildGraphFromViews(body, "headers");
  highlightAuthEndpoints(body.nodes);
  await loadSummary();
}

async function removeTrackedHeader(name) {
  const ws = $("#ws-select").value;
  if (ws) {
    const { body } = await api("/graph/headers?name=" + encodeURIComponent(name) +
      "&workspace_id=" + encodeURIComponent(ws), { method: "DELETE" });
    if (body?.tracked) { TRACKED_HEADERS = body.tracked; }
    else { TRACKED_HEADERS = TRACKED_HEADERS.filter((h) => h.toLowerCase() !== String(name).toLowerCase()); }
  } else {
    TRACKED_HEADERS = TRACKED_HEADERS.filter((h) => h.toLowerCase() !== String(name).toLowerCase());
  }
  persistTrackedHeaders();
  renderTrackedHeaderList();
  if (TRACKED_HEADERS.length) {
    await renderTrackedHeaders();
  } else {
    await runQuery();
  }
  await loadSummary();
}

function wireTrackedHeaders() {
  renderTrackedHeaderList();
  document.getElementById("btn-header-add").addEventListener("click", addTrackedHeader);
  document.getElementById("header-input").addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    addTrackedHeader();
  });
  document.getElementById("header-list").addEventListener("click", (e) => {
    const x = e.target.closest(".bi-x");
    if (x && x.dataset.header) removeTrackedHeader(x.dataset.header);
  });
  let t = null;
  document.getElementById("header-input").addEventListener("input", () => {
    clearTimeout(t);
    t = setTimeout(loadHeaderSuggestions, 220);
  });
}

// Layouts dagre: estáticos, sin animación, deterministas.
function dagreLayoutOpts() {
  return {
    name: "dagre",
    rankDir: "TB",
    nodeSep: layout.spring,
    rankSep: layout.repulsion,
    edgeSep: Math.round(layout.overlap * 30),
    animate: false,
    fit: true,
    padding: 40,
  };
}

// Posiciones persistidas por workspace (memoria espacial del analista)
function positionsKey() {
  const ws = $("#ws-select")?.value || "default";
  return "akg-pos-" + ws;
}
function loadSavedPositions() {
  try { return JSON.parse(localStorage.getItem(positionsKey()) || "{}"); } catch (_) { return {}; }
}
function savePositions() {
  if (!cy) return;
  const pos = {};
  cy.nodes().forEach((n) => { pos[n.id()] = { ...n.position() }; });
  try { localStorage.setItem(positionsKey(), JSON.stringify(pos)); } catch (_) {}
}
function clearSavedPositions() {
  try { localStorage.removeItem(positionsKey()); } catch (_) {}
}

function runLayout(useSaved = true) {
  if (!cy) return;
  const saved = useSaved ? loadSavedPositions() : {};
  const total = cy.nodes().length;
  const present = {};
  cy.nodes().forEach((n) => { if (saved[n.id()]) present[n.id()] = saved[n.id()]; });
  // solo reutiliza posiciones si cubren (casi) todos los nodos actuales
  if (total > 0 && Object.keys(present).length / total >= 0.8) {
    cy.layout({ name: "preset", positions: present, fit: true, padding: 40, animate: false }).run();
  } else {
    cy.layout(dagreLayoutOpts()).run();
  }
}

function nodeKey(nd) {
  if (!nd) return "?";
  const keys = Object.keys(nd).sort();
  return keys.map((k) => `${k}=${String(nd[k]).slice(0, 40)}`).join("|");
}

function nodeType(nd) {
  if (nd._kind) return nd._kind;
  const type = nd.type || nd.node_type || nd.kind || "";
  if (type) return type;
  const host = nd.host || nd.name || "";
  const pattern = nd.pattern || nd.path || "";
  if ((nd.method || pattern) && !host) return "Endpoint";
  if (host && !pattern && !nd.method) return "Host";
  if (nd.token || nd.token_value) return "Token";
  if (nd.cookie || nd.cookie_name) return "Cookie";
  return "?";
}

function nodeLabel(nd) {
  const host = nd.host || nd.name || "";
  const path = nd.pattern || nd.path || "";
  const method = nd.method || "";
  let label = "";
  if (method) label = method + " ";
  if (host && path) {
    const shortHost = host.replace(/^https?:\/\//, "").replace(/\/$/, "");
    label += shortHost.replace(/([^/]+)\/[^/]+.*/, "$1/…") + " " + path;
  } else if (host) {
    label += host.replace(/^https?:\/\//, "").replace(/\/$/, "");
  } else if (path) {
    label += path;
  } else {
    label += nd.id || nd.name || "?";
  }
  return label.slice(0, 48);
}

async function highlightAuthEndpoints(nodes) {
  try {
    const ws = $("#ws-select").value;
    const path = "/graph/auth-endpoints" + (ws ? `?workspace_id=${encodeURIComponent(ws)}` : "");
    const { ok, body } = await api(path);
    if (!ok || !body?.endpoints) return;
    const signalBy = new Map(body.endpoints.map((e) => [`${e.method}|${e.pattern}|${e.host || ""}`, e.signal]));
    nodes.forEach((n) => {
      const p = n.props || {};
      if (!p.method || !p.pattern) return;
      const signal = signalBy.get(`${p.method}|${p.pattern}|${p.host || ""}`);
      if (signal === "token" || signal === "cookie") {
        n._auth = signal;
        n.ring = AUTH_RING[signal];
      }
    });
    if (cy) {
      cy.batch(() => {
        nodes.forEach((n) => {
          if (!n.ring) return;
          const el = cy.getElementById(n.id);
          if (el.nonempty()) el.data("ring", n.ring);
        });
      });
    }
  } catch (_) { /* sin marcado */ }
}

// ── Leyenda clickeable: token / cookie / public / all ───────────────────
let _legendCache = null;
async function loadLegendData() {
  if (_legendCache) return _legendCache;
  const { ok, body } = await api("/graph/auth-endpoints");
  if (!ok || !body?.endpoints) return { token: [], cookie: [], public: [] };
  const idx = { token: [], cookie: [], public: [] };
  const hostSeen = { token: new Set(), cookie: new Set(), public: new Set() };
  body.endpoints.forEach((e) => {
    const s = idx[e.signal] || idx.public;
    const h = e.host || "";
    // endpoint: "GET host/pattern"
    const epLabel = `${e.method} ${h}${e.pattern}`;
    if (!s.some((x) => x.v === epLabel)) s.push({ kind: "endpoint", v: epLabel, q: epLabel });
    // subdominio unico por signal
    if (h && !hostSeen[e.signal].has(h)) {
      hostSeen[e.signal].add(h);
      s.push({ kind: "host", v: h, q: h });
    }
  });
  _legendCache = idx;
  return idx;
}

function renderLegendDropdowns(data) {
  document.querySelectorAll("#legend .legend-group").forEach((group) => {
    const signal = group.dataset.signal;
    const drop = group.querySelector(".legend-drop");
    if (signal === "all") { // boton directo, sin lista
      drop.innerHTML = "";
      return;
    }
    const items = data[signal] || [];
    const hosts = items.filter((i) => i.kind === "host");
    const eps = items.filter((i) => i.kind === "endpoint");
    const sec = (title, list) =>
      list.length
        ? `<div class="ld-head">${title} (${list.length})</div>` +
          list.map((i) => `<button class="ld-item" data-q="${escapeHtml(i.q)}">${escapeHtml(i.v)}</button>`).join("")
        : `<div class="ld-head">${title}</div><div class="ld-empty">sin coincidencias</div>`;
    drop.innerHTML = sec("subdominios", hosts) + sec("endpoints", eps);
  });
}

async function buildLegend() {
  const data = await loadLegendData();
  renderLegendDropdowns(data);
}

function applySignalFilter(q) {
  $("#node-label").value = q;
  runQuery();
}

function closeLegend() {
  document.querySelectorAll("#legend .legend-group.open").forEach((g) => g.classList.remove("open"));
}

function wireLegend() {
  $("#legend").addEventListener("click", async (e) => {
    const itemBtn = e.target.closest(".ld-item");
    if (itemBtn) { // click en un subdominio o endpoint de la lista
      closeLegend();
      applySignalFilter(itemBtn.dataset.q);
      return;
    }
    const btn = e.target.closest(".legend-btn");
    if (!btn) return;
    const group = btn.closest(".legend-group");
    const signal = group.dataset.signal;
    if (signal === "all") { // grafo completo sin filtros
      closeLegend();
      applySignalFilter("");
      return;
    }
    // toggle dropdown
    const wasOpen = group.classList.contains("open");
    closeLegend();
    if (!wasOpen) group.classList.add("open");
  });
  buildLegend();
}

function nodeSizeFor(total) {
  if (total > 500) return Math.max(5, layout.size * 0.5);
  if (total > 200) return Math.max(7, layout.size * 0.7);
  return layout.size;
}

function buildCyStyle(fontSize) {
  return [
    {
      selector: "node",
      style: {
        shape: "data(shape)",
        "background-color": "data(color)",
        "border-width": 1,
        "border-color": "data(border)",
        width: "data(size)",
        height: "data(size)",
        label: "data(label)",
        "font-family": "ui-monospace, SF Mono, Menlo, Consolas, monospace",
        "font-size": fontSize,
        color: LABEL_COLOR,
        "text-valign": "bottom",
        "text-halign": "center",
        "text-margin-y": 4,
        "text-max-width": "110px",
        "text-wrap": "ellipsis",
        "text-background-color": "#0d1117",
        "text-background-opacity": 0.7,
        "text-background-padding": 2,
      },
    },
    {
      // endpoints con señal de auth: anillo de color, el relleno no cambia
      selector: "node[?ring]",
      style: {
        "border-width": 2.5,
        "border-color": "data(ring)",
      },
    },
    {
      selector: "edge",
      style: {
        width: 1,
        "line-color": "data(color)",
        "target-arrow-color": "data(color)",
        "target-arrow-shape": "triangle",
        "arrow-scale": 0.8,
        "curve-style": "bezier",
        label: "",
        opacity: 0.6,
      },
    },
    // etiqueta de arista solo al pasar el ratón o al seleccionarla
    {
      selector: "edge:selected, edge.hover",
      style: {
        label: "data(label)",
        "font-family": "ui-monospace, SF Mono, Menlo, Consolas, monospace",
        "font-size": 9,
        color: "#c9d1d9",
        "text-rotation": "autorotate",
        "text-background-color": "#0d1117",
        "text-background-opacity": 0.85,
        "text-background-padding": 2,
        opacity: 1,
      },
    },
    {
      selector: "node:selected",
      style: {
        "border-width": 2,
        "border-color": ACCENT,
      },
    },
    {
      selector: ".dimmed",
      style: { opacity: 0.22, "text-opacity": 0.15 },
    },
    {
      selector: "edge.dimmed",
      style: { opacity: 0.08 },
    },
  ];
}

function renderGraph(nodes, edges, cypherType) {
  if (cy) { cy.destroy(); cy = null; }
  isolatedNodeId = null;
  originalGraphData = null;
  graphEl.innerHTML = "";

  const typeFiltered = nodes.filter((n) => NODE_TYPES_VISIBLE[nodeType(n)] !== false);
  const blockedFiltered = typeFiltered.filter((n) => !isBlockedNode(n));

  if (!blockedFiltered.length) {
    graphEl.innerHTML = "<div class='hint'>sin nodos para mostrar</div>";
    return;
  }

  const visibleIds = new Set(blockedFiltered.map((n) => n.id));
  const filteredEdges = edges.filter((e) => visibleIds.has(e.from) && visibleIds.has(e.to));

  const total = blockedFiltered.length;
  const isLargeGraph = total > 200;
  const isHuge = total > 500;

  // reducción de labels para grafos grandes: solo una fracción
  const showEvery = isHuge ? Math.max(1, Math.floor(total / 60)) : (isLargeGraph ? Math.max(1, Math.floor(total / 30)) : 1);

  const size = nodeSizeFor(total);
  const fontSize = isLargeGraph ? Math.max(8, layout.font * 0.8) : layout.font;

  const elements = [];
  blockedFiltered.forEach((n, i) => {
    const kind = n.group || nodeType(n);
    const c = NODE_COLORS[kind] || { bg: DEFAULT_BG, border: BORDER_SOFT };
    elements.push({
      group: "nodes",
      data: {
        id: n.id,
        label: (i % showEvery === 0) ? (n.label || "") : "",
        shape: NODE_SHAPES[kind] || "ellipse",
        color: c.bg,
        border: c.border,
        ring: n.ring || null,
        size: size,
      },
    });
  });
  filteredEdges.forEach((e, i) => {
    elements.push({
      group: "edges",
      data: {
        id: "e" + i,
        source: e.from,
        target: e.to,
        label: e.label || "",
        color: (e.color && e.color.color) || BORDER_SOFT,
      },
    });
  });

  cy = cytoscape({
    container: graphEl,
    elements,
    style: buildCyStyle(fontSize),
    wheelSensitivity: 0.2,
    minZoom: 0.05,
    maxZoom: 3,
  });
  window.__cy = cy;

  runLayout(true);

  // persistir posiciones al soltar un nodo (memoria espacial)
  cy.on("dragfree", "node", () => savePositions());
  cy.on("layoutstop", () => savePositions());

  cy.on("tap", "node", (e) => {
    const node = nodesById.get(e.target.id());
    if (node) showDetail(node);
  });
  cy.on("tap", (e) => { if (e.target === cy) { clearFocus(); closeDetail(); closeCtxMenu(); } });
  cy.on("cxttap", "node", (e) => {
    e.originalEvent.preventDefault();
    showCtxMenu(e.target.id(), e.originalEvent.clientX, e.originalEvent.clientY);
  });
  cy.on("cxttap", (e) => { if (e.target === cy) closeCtxMenu(); });

  // foco al pasar el ratón: ilumina vecinos, atenúa el resto
  if (!isLargeGraph) {
    cy.on("mouseover", "node", (e) => focusOnNode(e.target.id()));
    cy.on("mouseout", "node", () => clearFocus());
    cy.on("mouseover", "edge", (e) => e.target.addClass("hover"));
    cy.on("mouseout", "edge", (e) => e.target.removeClass("hover"));
  }

  lastGraph = { allNodes: nodes, allEdges: edges, cypherType };
  log(`grafo: ${blockedFiltered.length} nodos · ${filteredEdges.length} relaciones (${cypherType || "?"})${isLargeGraph ? " · optimizado" : ""}`, "ok");
  updateFilterCounts(nodes);
  renderBlockPickList();
}

// ── Foco: ilumina vecindad directa y atenúa el resto ────────────────────
function focusOnNode(nodeId) {
  if (!cy) return;
  const node = cy.getElementById(nodeId);
  if (node.empty()) return;
  cy.batch(() => {
    const neighborhood = node.closedNeighborhood();
    cy.elements().addClass("dimmed");
    neighborhood.removeClass("dimmed");
  });
}

function clearFocus() {
  if (!cy) return;
  cy.batch(() => cy.elements().removeClass("dimmed"));
}

// ── Menú contextual de nodo (click derecho) ─────────────────────────────
let ctxMenuEl = null;

function closeCtxMenu() {
  if (ctxMenuEl) { ctxMenuEl.remove(); ctxMenuEl = null; }
}

function showCtxMenu(nodeId, x, y) {
  closeCtxMenu();
  const node = nodesById.get(nodeId);
  if (!node) return;

  const menu = document.createElement("div");
  menu.className = "ctx-menu";

  const kind = document.createElement("div");
  kind.className = "ctx-kind";
  kind.textContent = (node.group || nodeType(node) || "nodo").toLowerCase();
  menu.appendChild(kind);

  const addItem = (label, fn, danger) => {
    const b = document.createElement("button");
    b.className = "ctx-item" + (danger ? " danger" : "");
    b.textContent = label;
    b.onclick = () => { closeCtxMenu(); fn(); };
    menu.appendChild(b);
  };

  addItem("Ver detalle", () => showDetail(node));
  if (isolatedNodeId) {
    addItem("Reintegrar grafo completo", restoreFullGraph);
  } else {
    addItem("Aislar vecindad", () => isolateNodeGraph(nodeId));
  }

  const props = node.props || {};
  const isHost = !!(props.host || props.name) && !props.method;
  const isEndpoint = !!(props.method && (props.pattern || props.path));
  if (isHost || isEndpoint) {
    const sep = document.createElement("div");
    sep.className = "ctx-sep";
    menu.appendChild(sep);
    const value = isEndpoint
      ? `${props.method} ${props.pattern || props.path}`
      : String(props.host || props.name).replace(/^https?:\/\//, "").replace(/\/$/, "");
    addItem(`Ocultar (${isHost ? "host" : "endpoint"})`, () => addBlock(value), true);
  }

  document.body.appendChild(menu);
  ctxMenuEl = menu;
  // clamp dentro de la ventana
  const rect = menu.getBoundingClientRect();
  menu.style.left = Math.min(x, window.innerWidth - rect.width - 8) + "px";
  menu.style.top = Math.min(y, window.innerHeight - rect.height - 8) + "px";
}

// ultimo grafo renderizado para re-render al cambiar el layout
let lastGraph = null;
let layoutTimer = null;

function rerenderLayout(relayout = false) {
  saveLayout();
  if (!lastGraph) return;
  clearTimeout(layoutTimer);
  layoutTimer = setTimeout(() => {
    if (relayout) clearSavedPositions();
    renderGraph(lastGraph.allNodes, lastGraph.allEdges, lastGraph.cypherType);
  }, 120);
}

const nodesById = new Map();

const $detail = $("#detail");
const $detailBody = $("#detail-body");

function showDetail(node) {
  if (!node) return;
  const props = node.props || {};
  const kind = (node.kind || "").toLowerCase();
  const isExchange = kind === "exchange" || !!props.exchange_id;
  const isEndpoint = kind === "endpoint" || (props.method && props.pattern);
  $("#detail-title").textContent = node.label || "Detalle";

  // renderizamos en HTML para poder incluir acciones
  $detailBody.innerHTML = "";
  const pre = document.createElement("pre");
  pre.textContent = Object.entries(props)
    .map(([k, v]) => `${k}: ${JSON.stringify(v)}`)
    .join("\n") || "sin propiedades";
  $detailBody.appendChild(pre);

  if (isExchange) {
    const btn = document.createElement("button");
    btn.className = "req-btn";
    btn.textContent = "Ver request original";
    btn.onclick = () => loadRawRequest(props.exchange_id, btn);
    $detailBody.appendChild(btn);
  } else if (isEndpoint) {
    const btn = document.createElement("button");
    btn.className = "req-btn";
    btn.textContent = "Ver request original (ejemplo)";
    btn.onclick = () => loadSampleRequest(props, btn);
    $detailBody.appendChild(btn);
  }
  $detail.classList.remove("hidden");
  renderIsolateActions(node);
}

// ── Aislar grafo ────────────────────────────────────────────────────────
let isolatedNodeId = null;
let originalGraphData = null;

function renderIsolateActions(node) {
  const old = document.getElementById("isolate-actions");
  if (old) old.remove();
  if (!node || !cy) return;

  const actions = document.createElement("div");
  actions.id = "isolate-actions";
  actions.style.cssText = "display:flex;gap:6px;margin-top:8px;";

  if (isolatedNodeId) {
    const restoreBtn = document.createElement("button");
    restoreBtn.className = "req-btn";
    restoreBtn.style.flex = "1";
    restoreBtn.textContent = "Reintegrar grafo completo";
    restoreBtn.onclick = restoreFullGraph;
    actions.appendChild(restoreBtn);
  } else {
    const isolateBtn = document.createElement("button");
    isolateBtn.className = "req-btn";
    isolateBtn.style.flex = "1";
    isolateBtn.textContent = "Aislar grafo";
    isolateBtn.onclick = () => isolateNodeGraph(node.id);
    actions.appendChild(isolateBtn);
  }

  $detailBody.appendChild(actions);
}

function isolateNodeGraph(nodeId) {
  if (!cy) return;
  originalGraphData = cy.elements().jsons();
  isolatedNodeId = nodeId;

  const node = cy.getElementById(nodeId);
  if (node.empty()) return;
  const neighborhood = node.closedNeighborhood();
  const keep = neighborhood.jsons();

  cy.elements().remove();
  cy.add(keep);
  cy.layout({ name: "dagre", rankDir: "TB", nodeSep: 48, rankSep: 120, animate: false, fit: true, padding: 60 }).run();

  const detailNode = document.getElementById("detail");
  if (detailNode) renderIsolateActions(nodesById.get(nodeId));
  log(`vista aislada: ${cy.nodes().length} nodos · ${cy.edges().length} relaciones`, "ok");
}

function restoreFullGraph() {
  if (!cy || !originalGraphData) return;
  isolatedNodeId = null;

  cy.elements().remove();
  cy.add(originalGraphData);
  runLayout(true);

  const old = document.getElementById("isolate-actions");
  if (old) old.remove();
  log("grafo completo restaurado", "ok");
}

async function loadSampleRequest(props, btn) {
  const importId = props.import_id;
  if (!importId) {
    btn.textContent = "nodo sin import_id";
    return;
  }
  const params = new URLSearchParams({ method: props.method, pattern: props.pattern });
  if (props.host) params.set("host", props.host);
  const { ok, body } = await api(`/imports/${importId}/sample-request?${params}`);
  if (!ok) {
    btn.textContent = body?.detail || "sin request de ejemplo";
    return;
  }
  renderRawRequestDetail(body);
  log(`request original de ${body.method} ${body.path}`, "ok");
}

async function loadRawRequest(exchangeId, btn) {
  const { ok, body } = await api(`/exchanges/${exchangeId}`);
  if (!ok) {
    btn.textContent = "error al obtener el request";
    return;
  }
  renderRawRequestDetail(body);
  log(`request original de ${body.method} ${body.path}`, "ok");
}

// ── Panel de request: JSON coloreado, colapsable y boton cURL ─────────────
function renderRawRequestDetail(d) {
  $("#detail-title").textContent = `Request · ${d.method} ${d.host}`;
  $detailBody.innerHTML = "";
  $detailBody.appendChild(buildRequestBlock(d, { raw: d.raw_request || "", showCurl: true }));
  $detail.classList.remove("hidden");
}

function buildRequestBlock(d, opts = {}) {
  const raw = opts.raw ?? d.raw_request ?? "";
  const container = document.createElement("div");
  container.className = "req-view";

  const idx = raw.indexOf("\r\n\r\n");
  const head = idx >= 0 ? raw.slice(0, idx) : raw;
  const payload = idx >= 0 ? raw.slice(idx + 4) : "";

  const preHead = document.createElement("pre");
  preHead.className = "dbg head";
  preHead.innerHTML = escapeHtml(head);
  container.appendChild(preHead);

  if (payload.trim()) {
    const looksJson = /^\s*[{[]/.test(payload);
    const wrap = document.createElement("div");
    wrap.className = "req-body";
    const pre = document.createElement("pre");
    pre.className = "dbg json";
    pre.innerHTML = looksJson ? highlightJson(payload) : escapeHtml(payload);
    if (payload.length > 800) {
      const details = document.createElement("details");
      details.className = "collapsible";
      const summary = document.createElement("summary");
      summary.textContent = `${looksJson ? "JSON" : "cuerpo"} (${payload.length} bytes)`;
      details.appendChild(summary);
      details.appendChild(pre);
      wrap.appendChild(details);
    } else {
      wrap.appendChild(pre);
    }
    container.appendChild(wrap);
  }

  if (opts.showCurl) {
    const curlBtn = document.createElement("button");
    curlBtn.className = "req-btn curl";
    curlBtn.textContent = "Copiar como cURL";
    curlBtn.onclick = () => copyCurl(opts.curlSource || d);
    container.appendChild(curlBtn);
  }
  return container;
}

function highlightJson(str) {
  let out = "";
  const esc = escapeHtml;
  const re = /("(?:\\.|[^"\\])*")(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/g;
  let last = 0;
  let m;
  while ((m = re.exec(str))) {
    out += esc(str.slice(last, m.index));
    const tok = m[0];
    if (m[1] !== undefined) {
      const colon = m[2] || "";
      out += `<span class="j-key">${esc(m[1])}</span>${colon ? `<span class="j-punc">${esc(colon)}</span>` : ""}`;
    } else if (tok === "true" || tok === "false") {
      out += `<span class="j-bool">${tok}</span>`;
    } else if (tok === "null") {
      out += `<span class="j-null">${tok}</span>`;
    } else if (tok.startsWith('"')) {
      out += `<span class="j-str">${esc(tok)}</span>`;
    } else {
      out += `<span class="j-num">${tok}</span>`;
    }
    last = re.lastIndex;
  }
  out += esc(str.slice(last));
  return out;
}

function shq(v) {
  return String(v).replace(/'/g, "'\\''");
}

function buildCurl(d) {
  const raw = d.raw_request || "";
  const firstLine = (raw.split("\r\n")[0] || "").split(" ");
  const method = firstLine[0] || d.method || "GET";
  const target = firstLine[1] || d.path || "/";
  const reqHeaders = (d.headers || []).filter((h) => h.direction === "request");
  const reqCookies = (d.cookies || []).filter((c) => c.direction === "request");
  const reqBody = (d.bodies || []).find((b) => b.direction === "request");
  const payload = reqBody && reqBody.body ? JSON.stringify(reqBody.body) : "";

  const lines = [`curl -X ${method} '${shq(d.scheme || "https")}://${shq(d.host)}${shq(target)}'`];
  reqHeaders.forEach((h) => lines.push(`  -H '${shq(h.name)}: ${shq(h.value || "")}'`));
  if (reqCookies.length) {
    lines.push(`  -H 'Cookie: ${reqCookies.map((c) => shq(`${c.name}=${c.value || ""}`)).join("; ")}'`);
  }
  if (payload) lines.push(`  --data-raw '${shq(payload)}'`);
  return lines.join(" \\\n");
}

async function copyCurl(d) {
  const text = buildCurl(d);
  try {
    await navigator.clipboard.writeText(text);
    log("cURL copiado al portapapeles", "ok");
  } catch (_) {
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    try {
      document.execCommand("copy");
      log("cURL copiado al portapapeles", "ok");
    } catch (e) {
      log("no se pudo copiar", "err");
    }
    document.body.removeChild(ta);
  }
}

function closeDetail() { $("#detail").classList.add("hidden"); }

// ── Vistas dedicadas (V0.1-37/38) ────────────────────────────────────
async function loadAuthFlow() {
  const ws = $("#ws-select").value;
  const path = "/graph/auth-flow" + (ws ? `?workspace_id=${encodeURIComponent(ws)}` : "");
  const { ok, body } = await api(path);
  if (!ok) { log("no hay flujos de autenticacion", "err"); return; }
  buildGraphFromViews(body, "auth-flow");
}

async function loadResources() {
  const ws = $("#ws-select").value;
  const path = "/graph/resources" + (ws ? `?workspace_id=${encodeURIComponent(ws)}` : "");
  const { ok, body } = await api(path);
  if (!ok) { log("no hay recursos", "err"); return; }
  buildGraphFromViews(body, "recursos");
}

const SEV_ORDER = { CRITICA: 4, ALTA: 3, MEDIA: 2, BAJA: 1, INFO: 0 };

async function loadFindings() {
  const ws = $("#ws-select").value;
  if (!ws) { log("selecciona un workspace primero", "err"); return; }
  const { body } = await api(`/imports?workspace_id=${ws}`);
  const imp = (body.items || []).find((i) => i.status === "MATERIALIZED");
  if (!imp) { log("no hay imports materializados en este workspace", "err"); return; }

  let alerts = [];
  const lst = await api(`/imports/${imp.id}/alerts`);
  if (lst.ok && lst.body.total > 0) {
    alerts = lst.body.items;
  } else {
    log("sin alertas previas: ejecutando reglas …", "");
    const run = await api(`/imports/${imp.id}/rules/run`, { method: "POST" });
    if (!run.ok) { log(`error al ejecutar reglas: ${run.body.error?.message || run.status}`, "err"); return; }
    log(`reglas ejecutadas: ${run.body.alerts_created} alertas`, "ok");
    const l2 = await api(`/imports/${imp.id}/alerts`);
    alerts = l2.body.items;
  }

  alerts.sort((a, b) => (SEV_ORDER[b.severity] || 0) - (SEV_ORDER[a.severity] || 0));
  renderFindings(alerts, imp.id);
}

function renderFindings(alerts, importId) {
  const root = $("#graph");
  root.innerHTML = "";
  const wrap = document.createElement("div");
  wrap.className = "findings";
  wrap.innerHTML = `
    <div class="findings-head">
      <h3>Findings · ${alerts.length} alertas</h3>
      <span class="muted">import ${importId.slice(0, 8)}…</span>
    </div>`;
  if (!alerts.length) {
    wrap.innerHTML += `<div class="finding empty">Sin hallazgos de riesgo.</div>`;
    root.appendChild(wrap);
    return;
  }
  const counts = {};
  alerts.forEach((a) => { counts[a.severity] = (counts[a.severity] || 0) + 1; });
  const legend = Object.entries(counts)
    .map(([s, n]) => `<span class="sev sev-${s}">${s}: ${n}</span>`)
    .join(" ");
  wrap.innerHTML += `<div class="findings-legend">${legend}</div>`;

  alerts.forEach((a) => {
    const card = document.createElement("div");
    card.className = `finding sev-${a.severity}`;
    card.innerHTML = `
      <div class="finding-row">
        <span class="sev-badge">${a.severity}</span>
        <span class="finding-title">${escapeHtml(a.title)}</span>
        <span class="muted">${escapeHtml(a.rule_id)}</span>
      </div>
      <div class="finding-meta muted">${a.status} · conf ${a.confidence ?? "—"}</div>`;
    card.onclick = () => showFindingDetail(a.id);
    wrap.appendChild(card);
  });
  root.appendChild(wrap);
  closeDetail();
}

async function showFindingDetail(alertId) {
  const { ok, body } = await api(`/alerts/${alertId}`);
  if (!ok) { log("no se pudo abrir la alerta", "err"); return; }
  const ev = body.evidence || {};
  const fields = ev.fields || {};

  // request original real (primer exchange implicado)
  let original = null;
  if (body.exchange_ids && body.exchange_ids.length) {
    const r = await api(`/exchanges/${body.exchange_ids[0]}`);
    if (r.ok) original = r.body;
  }
  const testReq = original ? buildTestRequest(original, fields, body.rule_id) : null;

  const el = document.createElement("div");
  el.className = "finding-detail";

  el.innerHTML = `
    <div class="fd-head">
      <span class="sev sev-${body.severity}">${body.severity}</span>
      <div>
        <h3 class="fd-title">${escapeHtml(body.title)}</h3>
        <div class="fd-meta muted">${escapeHtml(body.rule_id)} · ${body.status} · conf ${body.confidence ?? "—"}</div>
      </div>
    </div>

    <section class="fd-sec">
      <h4>Descripción</h4>
      <p class="fd-desc">${escapeHtml(body.description || "—")}</p>
      ${buildImpactHint(body.rule_id)}
    </section>

    <section class="fd-sec">
      <h4>Detalles</h4>
      <dl class="fd-dl">
        ${Object.entries(fields).map(([k, v]) => `<dt>${escapeHtml(k)}</dt><dd>${escapeHtml(String(v))}</dd>`).join("")}
        ${body.host ? `<dt>subdominio</dt><dd>${escapeHtml(body.host)}</dd>` : ""}
      </dl>
    </section>

    <section class="fd-sec">
      <h4>Evidencia</h4>
      <p class="fd-exchanges muted">${(body.exchange_ids || []).length} exchange(s) implicado(s)</p>
      <ul class="fd-list">
        ${(body.node_keys || []).map((k) => `<li>${escapeHtml(k)}</li>`).join("")}
      </ul>
      <details class="collapsible">
        <summary>IDs de exchanges</summary>
        <pre class="dbg">${escapeHtml((body.exchange_ids || []).join("\n") || "—")}</pre>
      </details>
    </section>
  `;

  if (original) {
    const origSec = document.createElement("section");
    origSec.className = "fd-sec";
    origSec.innerHTML = `<h4>Ejemplo de petición original</h4>`;
    origSec.appendChild(buildRequestBlock(original, { showCurl: true }));
    el.appendChild(origSec);
  }

  if (testReq) {
    const testSec = document.createElement("section");
    testSec.className = "fd-sec";
    testSec.innerHTML = `
      <h4>Ejemplo de petición para testing</h4>
      <p class="fd-hint muted">${escapeHtml(testReq.hint)}</p>`;
    testSec.appendChild(buildRequestBlock(testReq.detail, { showCurl: true }));
    el.appendChild(testSec);
  }

  $("#detail-title").textContent = `Finding ${body.severity}`;
  $detailBody.innerHTML = "";
  $detailBody.appendChild(el);
  $("#detail").classList.remove("hidden");
}

// ── Helpers para el detalle del finding ──────────────────────────────────────
function buildImpactHint(ruleId) {
  const hints = {
    "R-IDOR-001":
      "<p class='fd-hint'>Impacto: acceso cruzado a objetos de otros usuarios alterando el ID en el path.</p>",
    "R-IDOR-004":
      "<p class='fd-hint'>Impacto: lectura de recursos por ID sin autenticación/autorización observada.</p>",
    "R-AUTH-001":
      "<p class='fd-hint'>Impacto: recurso accesible sin credenciales; confirmar si debería exigir auth.</p>",
    "R-INFRA-001":
      "<p class='fd-hint'>Impacto: tráfico en claro susceptible a intercepción/Man-in-the-Middle.</p>",
    "R-AUTH-003":
      "<p class='fd-hint'>Impacto: credenciales/secrets expuestos en query string (logs, referers, proxies).</p>",
  };
  return hints[ruleId] || "";
}

function buildTestRequest(original, fields, ruleId) {
  const method = original.method || "GET";
  const reqHeaders = (original.headers || []).filter((h) => h.direction === "request");
  const reqCookies = (original.cookies || []).filter((c) => c.direction === "request");
  const reqBody = (original.bodies || []).find((b) => b.direction === "request");

  let target = original.path || "/";
  let hint = "Reenviar la petición y comparar la respuesta con la original.";

  if (/R-IDOR/.test(ruleId)) {
    // muta el valor del id en el path para probar acceso cruzado
    target = mutatePathId(target);
    hint =
      "Sustituye el ID del recurso por otro valor (p.ej. 1 -> 9999) y comprueba " +
      "si responde con datos ajenos sin autorización (status 200 vs 403/404).";
  } else if (ruleId === "R-AUTH-001") {
    hint =
      "Envía la petición sin cookies ni token y verifica si el endpoint devuelve " +
      "datos (200) en lugar de exigir autenticación (401/403).";
  } else if (ruleId === "R-INFRA-001") {
    hint =
      "Confirmar el servicio en HTTP plano y verificar si redirige a HTTPS o expone " +
      "datos en claro sobre el cable.";
  }

  const detail = {
    method,
    host: original.host,
    scheme: original.scheme || "https",
    path: target,
    headers: original.headers,
    cookies: original.cookies,
    bodies: original.bodies,
    raw_request: rewriteRawRequest(original.raw_request, method, target, ruleId),
  };
  return { detail, hint };
}

function mutatePathId(path) {
  // reemplaza el último segmento que parezca un id (uuid o entero) por otro valor
  const segs = path.split("/");
  for (let i = segs.length - 1; i > 0; i--) {
    const s = segs[i];
    if (/^[0-9a-f]{8}-[0-9a-f-]{27,}$/i.test(s)) {
      segs[i] = "00000000-0000-4000-8000-000000000001";
      break;
    }
    if (/^\d+$/.test(s)) {
      segs[i] = "9999";
      break;
    }
  }
  return segs.join("/");
}

function rewriteRawRequest(raw, method, target, ruleId) {
  const lines = (raw || "").split("\r\n");
  if (!lines.length) return `${method} ${target} HTTP/1.1\r\n`;
  lines[0] = `${method} ${target} HTTP/1.1`;
  if (ruleId === "R-AUTH-001") {
    const kept = lines.filter(
      (l) => !/^cookie:/i.test(l) && !/^authorization:/i.test(l)
    );
    kept.splice(1, 0, "# testing: sin cookies ni Authorization");
    return kept.join("\r\n");
  }
  return lines.join("\r\n");
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function buildGraphFromViews(body, kind) {
  nodesById.clear();
  const nodes = (body.nodes || []).map((nd, i) => {
    const lab = (nd.labels || ["?"])[0];
    const node = {
      id: nd.id || String(i),
      label: nodeLabel(nd.properties),
      group: lab,
      props: nd.properties,
      _kind: lab,
    };
    nodesById.set(node.id, node);
    return node;
  });
  const edges = (body.edges || []).map((e) => ({
    from: e.source,
    to: e.target,
    label: e.type.slice(0, 12),
    arrows: "to",
  }));
  renderGraph(nodes, edges, kind);
  highlightAuthEndpoints(nodes);
}

async function runQuery() {
  nodesById.clear();
  const raw = $("#node-label").value.trim();
  const limit = $("#node-limit") ? $("#node-limit").value : 80;
  const ws = $("#ws-select").value;
  let body;
  let mode = "semantico";
  if (raw) {
    const path = `/graph/filter?q=${encodeURIComponent(raw)}&limit=${Number(limit) || 80}` +
      (ws ? `&workspace_id=${encodeURIComponent(ws)}` : "");
    const { ok, status, body: fb } = await api(path);
    if (!ok) { log(`filtro rechazado: ${fb?.detail || status}`, "err"); return; }
    body = fb;
    mode = `filtro: ${raw}`;
  } else {
    const cypher = `MATCH (a)-[r]->(b) WHERE NOT a:Exchange AND NOT b:Exchange ` +
      `AND type(r) <> 'SENDS' AND type(r) <> 'RECEIVES' ` +
      (ws ? `AND a.project = $project_id AND r.project = $project_id ` : "") +
      `RETURN a, r, b, properties(r) AS rprops, labels(a) AS alabels, labels(b) AS blabels LIMIT ${Number(limit) || 80}`;
    const payload = { cypher };
    if (ws) payload.params = { project_id: ws };
    const queryParams = ws ? `?workspace_id=${encodeURIComponent(ws)}` : "";
    const { ok, status, body: b } = await api(`/graph/query${queryParams}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!ok) { log(`consulta rechazada: ${b?.detail || status}`, "err"); return; }
    body = b;
  }

  const seen = new Map();
  const nodes = [];
  const edges = [];
  const primaryLabel = (labels) => (Array.isArray(labels) && labels.length ? labels[0] : "?");
  const pushNode = (nd, labels) => {
    if (!nd) return null;
    const id = nodeKey(nd);
    if (!seen.has(id)) {
      seen.set(id, true);
      const lab = primaryLabel(labels);
      nodes.push({
        id,
        label: nodeLabel(nd),
        group: lab,
        props: nd,
        _kind: lab,
      });
    }
    return id;
  };
  // evita colisiones de id dentro de una misma fila
  body.forEach((row) => {
    const a = row.a;
    const b = row.b;
    const r = row.r;
    const fromId = pushNode(a, row.alabels);
    const toId = pushNode(b, row.blabels);
    if (fromId && toId) {
      const type = Array.isArray(r) ? String(r[1] || "REL") : "REL";
      const conf = row.rprops ? String(row.rprops.confidence || "") : "";
      edges.push({
        from: fromId,
        to: toId,
        label: type.slice(0, 10) + (conf ? ` · ${conf.slice(0, 3)}` : ""),
        arrows: "to",
        color: { color: CONF_COLORS[conf] || "#30363d" },
      });
    }
  });
  // si viene `n` solo, render mal formado pero tolerante
  if (!nodes.length) {
    body.forEach((row) => {
      const nd = row.n || row.node || row;
      pushNode(nd, row.nlabels);
    });
  }
  nodes.forEach((n) => nodesById.set(n.id, n));
  renderGraph(nodes, edges, mode);
  highlightAuthEndpoints(nodes); // pinta en azul los endpoints que usan auth
}

// ── Autocompletado del buscador (sugerencias de hosts/endpoints) ─────────
let suggestTimer = null;
$("#node-label").addEventListener("input", () => {
  clearTimeout(suggestTimer);
  suggestTimer = setTimeout(loadSuggestions, 180);
});

async function loadSuggestions() {
  const dl = $("#labels-list");
  if (!dl) return;
  const q = $("#node-label").value.trim();
  if (!q) { dl.innerHTML = ""; return; }
  const ws = $("#ws-select").value;
  const path = `/graph/suggestions?q=${encodeURIComponent(q)}` + (ws ? `&workspace_id=${encodeURIComponent(ws)}` : "");
  const { ok, body } = await api(path);
  if (!ok || !body?.suggestions) return;
  dl.innerHTML = body.suggestions
    .map((s) => `<option value="${escapeHtml(s)}"></option>`)
    .join("");
}

// ── wiring ──────────────────────────────────────────────────────────────
$("#btn-new-ws").onclick = createWorkspace;
$("#btn-del-ws").onclick = deleteWorkspace;
$("#btn-upload").onclick = () => $("#file-input").click();
$("#file-input").onchange = (e) => e.target.files[0] && uploadFile(e.target.files[0]);
$("#btn-query").onclick = runQuery;
$("#node-label").addEventListener("keydown", (e) => e.key === "Enter" && runQuery());
$("#btn-clear-filter").addEventListener("click", () => {
  $("#node-label").value = "";
  $("#labels-list").innerHTML = "";
  runQuery();
});
$("#ws-select").addEventListener("change", () => {
  _legendCache = null;
  loadSummary();
  runQuery();
  buildLegend();
  syncTrackedHeaders(false);
});
$("#detail-close").onclick = closeDetail;

// ── controles de layout ─────────────────────────────────────────────────
const LAYOUT_SLIDERS = {
  size: { el: "#adj-size", v: "#adj-size-v", fmt: (v) => v + " px" },
  spring: { el: "#adj-spring", v: "#adj-spring-v", fmt: (v) => v + " px" },
  repulsion: { el: "#adj-repulsion", v: "#adj-repulsion-v", fmt: (v) => v.toLocaleString("es") },
  overlap: { el: "#adj-overlap", v: "#adj-overlap-v", fmt: (v) => (v * 100).toFixed(0) + "%" },
  font: { el: "#adj-font", v: "#adj-font-v", fmt: (v) => v + " px" },
};

function syncLayoutControls() {
  Object.entries(LAYOUT_SLIDERS).forEach(([key, cfg]) => {
    const slider = $(cfg.el);
    if (!slider) return;
    const val = key === "overlap" ? Math.round(layout[key] * 100) : layout[key];
    slider.value = val;
    if ($(cfg.v)) $(cfg.v).textContent = cfg.fmt(layout[key]);
  });
}

function setPreset(name) {
  clearSavedPositions();
  activePreset = name;
  layout = { ...LAYOUT_PRESETS[name] };
  syncLayoutControls();
  saveLayout();
  rerenderLayout();
  document.querySelectorAll(".preset-btn").forEach((b) => b.classList.remove("active"));
  $(`#preset-${name}`).classList.add("active");
}

$("#preset-dense").onclick = () => setPreset("dense");
$("#preset-compact").onclick = () => setPreset("compact");
$("#preset-balanced").onclick = () => setPreset("balanced");
$("#preset-expanded").onclick = () => setPreset("expanded");
const presetBtn = $(`#preset-${activePreset}`);
if (presetBtn) presetBtn.classList.add("active");

Object.entries(LAYOUT_SLIDERS).forEach(([key, cfg]) => {
  const slider = $(cfg.el);
  if (!slider) return;
  slider.addEventListener("input", () => {
    layout[key] = cfg.el === "#adj-overlap" ? Number(slider.value) / 100 : Number(slider.value);
    if ($(cfg.v)) $(cfg.v).textContent = cfg.fmt(layout[key]);
    activePreset = "custom";
    document.querySelectorAll(".preset-btn").forEach(b => b.classList.remove("active"));
    saveLayout();
    rerenderLayout(true);
  });
});

$("#layout-reset").onclick = () => {
  setPreset("balanced");
};

$("#btn-fit").onclick = () => {
  if (cy) cy.fit(null, 40);
};

function buildNodeTypeFilters() {
  const container = $("#node-type-filters");
  if (!container) return;
  const kinds = Object.keys(NODE_COLORS);
  container.innerHTML = kinds.map((k) => {
    const c = NODE_COLORS[k];
    const checked = NODE_TYPES_VISIBLE[k] !== false;
    return `<label class="ntf-toggle ${checked ? "on" : ""}" data-kind="${k}" style="--ntf-color:${c.bg};--ntf-border:${c.border}">
      <span class="ntf-dot" aria-hidden="true"></span> ${k}
    </label>`;
  }).join("");

  container.addEventListener("click", (e) => {
    const lbl = e.target.closest(".ntf-toggle");
    if (!lbl) return;
    const kind = lbl.dataset.kind;
    NODE_TYPES_VISIBLE[kind] = !(NODE_TYPES_VISIBLE[kind] !== false);
    lbl.classList.toggle("on", NODE_TYPES_VISIBLE[kind] !== false);
    applyNodeTypeFilter();
  });
}

function updateFilterCounts(allNodes) {
  const container = $("#node-type-filters");
  if (!container) return;
  const counts = {};
  (allNodes || []).forEach((n) => {
    const t = nodeType(n);
    counts[t] = (counts[t] || 0) + 1;
  });
  container.querySelectorAll(".ntf-toggle").forEach((lbl) => {
    const kind = lbl.dataset.kind;
    const count = counts[kind] || 0;
    let textEl = lbl.querySelector(".ntf-count");
    if (!textEl) {
      textEl = document.createElement("span");
      textEl.className = "ntf-count";
      lbl.appendChild(textEl);
    }
    textEl.textContent = count;
  });
}
syncLayoutControls();

const VIEWS = {
  "view-semantic": runQuery,
  "view-auth": loadAuthFlow,
  "view-resources": loadResources,
  "view-findings": loadFindings,
};
Object.entries(VIEWS).forEach(([id, fn]) => {
  $(`#${id}`).onclick = () => {
    Object.keys(VIEWS).forEach((k) => $("#" + k).classList.remove("active"));
    $("#" + id).classList.add("active");
    closeDetail();
    fn();
  };
});

(async () => {
  try { await loadWorkspaces(); } catch(e) { console.error("INIT FAILED", e); }
})();

wireLegend();
buildNodeTypeFilters();
wireBlocklist();
wireTrackedHeaders();

document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
    e.preventDefault();
    const inp = $("#node-label");
    if (inp) { inp.focus(); inp.select(); }
    return;
  }
  if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA" || e.target.tagName === "SELECT") return;
  if (e.key === "f" || e.key === "F") {
    e.preventDefault();
    if (cy) cy.fit(null, 40);
  }
  if (e.key === "r" || e.key === "R") {
    e.preventDefault();
    clearSavedPositions();
    rerenderLayout(true);
    log("re-layout (dagre) ejecutado", "");
  }
  if (e.key === "Escape") {
    closeCtxMenu();
    closeDetail();
  }
});

document.addEventListener("click", (e) => {
  if (ctxMenuEl && !e.target.closest(".ctx-menu")) closeCtxMenu();
});

(function initSidebarResize() {
  const sidebar = document.getElementById("sidebar");
  const handle = sidebar?.querySelector(".sidebar-resize");
  if (!sidebar || !handle) return;

  let saved = localStorage.getItem("akg-sidebar-w");
  if (saved) sidebar.style.setProperty("--sidebar-w", saved + "px");

  let dragging = false;
  let startX = 0;
  let startW = 0;

  handle.addEventListener("mousedown", (e) => {
    dragging = true;
    startX = e.clientX;
    startW = sidebar.offsetWidth;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    e.preventDefault();
  });

  document.addEventListener("mousemove", (e) => {
    if (!dragging) return;
    const delta = e.clientX - startX;
    const w = Math.max(220, Math.min(600, startW + delta));
    sidebar.style.setProperty("--sidebar-w", w + "px");
  });

  document.addEventListener("mouseup", () => {
    if (!dragging) return;
    dragging = false;
    document.body.style.cursor = "";
    document.body.style.userSelect = "";
    const w = sidebar.offsetWidth;
    try { localStorage.setItem("akg-sidebar-w", w); } catch (_) {}
  });
})();