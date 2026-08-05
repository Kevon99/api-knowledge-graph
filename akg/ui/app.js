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
async function loadWorkspaces() {
  const { ok, body } = await api("/workspaces");
  if (!ok) return;
  const sel = $("#ws-select");
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
  if (!id) return;
  if (!confirm(`¿Eliminar el workspace "${name}" y todo su contenido?`)) return;
  const { ok } = await api(`/workspaces/${encodeURIComponent(id)}`, { method: "DELETE" });
  log(ok ? `workspace "${name}" eliminado` : "error al eliminar", ok ? "ok" : "err");
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

// ── Grafo (consulta Cypher → vis-network) ───────────────────────────────
let network = null;

const NODE_COLORS = {
  Host: { bg: "#4c72b0", border: "#2a4a8a", icon: "🖥" },
  Endpoint: { bg: "#55a868", border: "#33703d", icon: "⚡" },
  Token: { bg: "#e74c3c", border: "#b03a2e", icon: "🔑" },
  Cookie: { bg: "#9b59b6", border: "#7d3c98", icon: "🍪" },
  Session: { bg: "#f39c12", border: "#d68910", icon: "📋" },
  Resource: { bg: "#3498db", border: "#1f6fa8", icon: "📄" },
  Flow: { bg: "#e67e22", border: "#c06514", icon: "🔀" },
  AuthFlow: { bg: "#ff6b3d", border: "#cc5028", icon: "🔐" },
  Exchange: { bg: "#7f8c8d", border: "#5d6d6d", icon: "📨" },
};

const DEFAULT_BG = "#95a5a6";

const CONF_COLORS = { EVIDENCIA: "#27ae60", INFERENCIA: "#f1c40f" };

const NODE_SHAPES = {
  Host: "hexagon",
  Endpoint: "dot",
  Token: "diamond",
  Cookie: "triangle",
  Session: "square",
  Resource: "box",
  Flow: "star",
  AuthFlow: "star",
  Exchange: "dot",
};

// ── Ajustes de layout (persistidos en localStorage) ─────────────────────
const LAYOUT_PRESETS = {
  dense: { spring: 60, repulsion: 3000, overlap: 0.3, size: 8, font: 8, damping: 0.3, centralGravity: 0.3 },
  compact: { spring: 130, repulsion: 6000, overlap: 0.4, size: 14, font: 10, damping: 0.2, centralGravity: 0.15 },
  balanced: { spring: 220, repulsion: 8000, overlap: 0.5, size: 18, font: 12, damping: 0.12, centralGravity: 0.08 },
  expanded: { spring: 380, repulsion: 18000, overlap: 0.7, size: 24, font: 14, damping: 0.08, centralGravity: 0.04 },
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

function physicsOptions(totalNodes) {
  const n = totalNodes || 0;
  const big = n > 150;
  return {
    enabled: true,
    solver: "barnesHut",
    barnesHut: {
      gravitationalConstant: big ? -Math.min(layout.repulsion * 0.3, 3000) : -layout.repulsion,
      centralGravity: big ? 0.12 : (layout.centralGravity ?? 0.08),
      springLength: big ? Math.max(100, layout.spring * 0.7) : layout.spring,
      springConstant: big ? 0.008 : 0.015,
      damping: big ? 0.3 : (layout.damping ?? 0.12),
      avoidOverlap: big ? 0.6 : layout.overlap,
    },
    stabilization: { iterations: big ? 400 : 300, updateInterval: 25 },
    maxVelocity: big ? 2 : 4,
    minVelocity: 0.4,
    timestep: big ? 0.5 : 0.35,
  };
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

const AUTH_SIGNAL_COLORS = {
  token: { background: "#4f8cff", border: "#1c5cb8" },
  cookie: { background: "#ffc857", border: "#b8871c" },
};

async function highlightAuthEndpoints(nodes) {
  try {
    const ws = $("#ws-select").value;
    const path = "/graph/auth-endpoints" + (ws ? `?workspace_id=${encodeURIComponent(ws)}` : "");
    const { ok, body } = await api(path);
    if (!ok || !body?.endpoints) return;
    const signalBy = new Map(body.endpoints.map((e) => [`${e.method}|${e.pattern}|${e.host || ""}`, e.signal]));
    const updates = [];
    nodes.forEach((n) => {
      const p = n.props || {};
      if (!p.method || !p.pattern) return;
      const signal = signalBy.get(`${p.method}|${p.pattern}|${p.host || ""}`);
      if (signal === "token" || signal === "cookie") {
        n.color = AUTH_SIGNAL_COLORS[signal];
        n._auth = signal;
        updates.push({ id: n.id, color: n.color });
      }
    });
    if (updates.length && network) {
      const present = network.body.data.nodes.get({ returnType: "Object" });
      network.body.data.nodes.update(updates.filter((u) => present[u.id]));
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

function renderGraph(nodes, edges, cypherType) {
  if (network) { network.destroy(); network = null; }
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

  // reduccion de labels para grafos grandes
  if (isLargeGraph) {
    const showEvery = isHuge ? Math.max(1, Math.floor(total / 80)) : Math.max(1, Math.floor(total / 40));
    let idx = 0;
    blockedFiltered.forEach((n) => {
      n.label = (idx++ % showEvery === 0) ? n.label : "";
    });
  }

  const data = { nodes: new vis.DataSet(blockedFiltered), edges: new vis.DataSet(filteredEdges) };

  const groups = {};
  Object.entries(NODE_COLORS).forEach(([kind, c]) => {
    groups[kind] = {
      shape: isHuge ? "dot" : (NODE_SHAPES[kind] || "dot"),
      color: { background: c.bg, border: c.border, highlight: { background: c.bg, border: "#fff" } },
      borderWidth: isLargeGraph ? 0.6 : 1.5,
      size: isLargeGraph ? Math.max(6, layout.size * 0.55) : layout.size,
      font: { size: isLargeGraph ? Math.max(8, layout.font * 0.7) : layout.font, color: "#e0e4f0",
        face: "ui-sans-serif,system-ui", strokeWidth: isLargeGraph ? 1 : 2, strokeColor: "#0f1117" },
    };
  });

  const baseSize = isHuge ? 6 : (isLargeGraph ? 9 : layout.size);

  const opts = {
    nodes: {
      shape: "dot",
      size: baseSize,
      scaling: { min: isHuge ? 4 : (isLargeGraph ? 6 : 10), max: isLargeGraph ? 28 : 38,
        label: { enabled: true, min: isLargeGraph ? 7 : 10, max: 13, drawThreshold: isLargeGraph ? 8 : 3 } },
      font: { size: isLargeGraph ? Math.max(8, layout.font * 0.7) : layout.font, color: "#e0e4f0",
        face: "ui-sans-serif,system-ui", strokeWidth: isLargeGraph ? 1 : 2, strokeColor: "#0f1117" },
      borderWidth: isLargeGraph ? 0.6 : 1.5,
      borderWidthSelected: 3,
      color: { background: DEFAULT_BG, border: "#555", highlight: { background: DEFAULT_BG, border: "#fff" } },
      shadow: { enabled: !isLargeGraph, color: "rgba(0,0,0,0.3)", size: 6, x: 2, y: 2 },
      mass: isHuge ? 0.3 : (isLargeGraph ? 0.6 : 1),
    },
    edges: {
      arrows: { to: { enabled: !isLargeGraph, scaleFactor: 0.7 } },
      smooth: isHuge ? false : (isLargeGraph ? { type: "continuous" } : { type: "curvedCW", roundness: 0.2 }),
      width: isHuge ? 0.4 : (isLargeGraph ? 0.6 : 1.5),
      widthConstraint: { maximum: isLargeGraph ? 1.5 : 3 },
      font: { size: 7, align: "middle", color: "#666", strokeWidth: 0 },
      color: { color: isHuge ? "#2a2a3a" : (isLargeGraph ? "#3a3a4a" : "#555"), highlight: "#4f8cff", hover: "#4f8cff" },
      hoverWidth: 0,
      selectionWidth: 0,
    },
    groups: groups,
    interaction: {
      hover: !isLargeGraph,
      hoverConnectedEdges: false,
      tooltipDelay: 100,
      navigationButtons: true,
      keyboard: { enabled: true, speed: { x: 10, y: 10, zoom: 0.02 } },
      zoomView: true,
      dragView: true,
      hideEdgesOnDrag: isLargeGraph,
      hideEdgesOnZoom: isLargeGraph,
    },
    layout: {
      improvedLayout: true,
      randomSeed: 1,
    },
    physics: physicsOptions(total),
    configure: { enabled: false },
  };

  network = new vis.Network(graphEl, data, opts);
  window.__network = network;

  if (isLargeGraph) {
    network.on("stabilized", () => {
      network.setOptions({ physics: { solver: "barnesHut", barnesHut: {
        gravitationalConstant: -800, centralGravity: 0.06, springLength: 160,
        springConstant: 0.005, damping: 0.35, avoidOverlap: 0.8 } },
        maxVelocity: 1.5, minVelocity: 0.3 });
      setTimeout(() => {
        if (network) {
          network.storePositions();
          network.setOptions({ physics: { enabled: false } });
        }
      }, 2500);
    });
  } else {
    network.on("stabilizationIterationsDone", () => {
      network.setOptions({ physics: { solver: "barnesHut", barnesHut: {
        gravitationalConstant: physicsOptions().barnesHut.gravitationalConstant * 0.4,
        centralGravity: physicsOptions().barnesHut.centralGravity,
        springLength: physicsOptions().barnesHut.springLength * 1.1,
        springConstant: 0.008,
        damping: 0.12,
        avoidOverlap: physicsOptions().barnesHut.avoidOverlap,
      } }, maxVelocity: 2, minVelocity: 0.2 });
    });
  }

  network.on("click", (params) => {
    const { nodes: clicked } = params;
    if (clicked && clicked.length) showDetail(nodesById.get(clicked[0]));
    else closeDetail();
  });

  if (!isLargeGraph) {
    network.on("hoverNode", (params) => focusOnNode(params.node));
    network.on("blurNode", () => clearFocus());
  }

  lastGraph = { allNodes: nodes, allEdges: edges, cypherType };
  log(`grafo: ${blockedFiltered.length} nodos * ${filteredEdges.length} relaciones (${cypherType || "?"})${isLargeGraph ? " · optimizado" : ""}`, "ok");
  updateFilterCounts(nodes);
  renderBlockPickList();
  if (network) log(`zoom+/scroll para navegar, F para encuadrar`, "");
}

// ── Foco al pasar el mouse: ilumina conexiones directas y atenúa el resto ──
let focusTimer = null;

function focusOnNode(nodeId) {
  if (!network) return;
  clearTimeout(focusTimer);
  const nodeDS = network.body.data.nodes;
  const edgeDS = network.body.data.edges;
  const connected = new Set([nodeId]);
  const connectedEdges = new Set();

  edgeDS.get().forEach((e) => {
    const isConn = e.from === nodeId || e.to === nodeId;
    if (isConn) {
      connected.add(e.from);
      connected.add(e.to);
      connectedEdges.add(e.id);
    }
  });

  const nodeUpdates = nodeDS.get().map((n) => ({
    id: n.id,
    opacity: connected.has(n.id) ? 1 : 0.12,
    borderWidth: n.id === nodeId ? 3 : (connected.has(n.id) ? 2 : 0.5),
  }));

  const edgeUpdates = edgeDS.get().map((e) => ({
    id: e.id,
    opacity: connectedEdges.has(e.id) ? 1 : 0.04,
    width: connectedEdges.has(e.id) ? 2.5 : 0.5,
  }));

  nodeDS.update(nodeUpdates);
  edgeDS.update(edgeUpdates);
}

function clearFocus() {
  if (!network) return;
  focusTimer = setTimeout(() => {
    const nodeDS = network.body.data.nodes;
    const edgeDS = network.body.data.edges;
    nodeDS.get().forEach((n) => nodeDS.update({ id: n.id, opacity: 1, borderWidth: 1.5 }));
    edgeDS.get().forEach((e) => edgeDS.update({ id: e.id, opacity: 1, width: 1.5 }));
  }, 60);
}

// ultimo grafo renderizado para re-render al cambiar el layout
let lastGraph = null;
let layoutTimer = null;

function rerenderLayout() {
  saveLayout();
  if (!lastGraph) return;
  clearTimeout(layoutTimer);
  layoutTimer = setTimeout(() => {
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
  if (!node || !network) return;

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
    isolateBtn.style.background = "rgba(79,140,255,0.15)";
    isolateBtn.style.color = "#79a9ff";
    isolateBtn.textContent = "Aislar grafo";
    isolateBtn.onclick = () => isolateNodeGraph(node.id);
    actions.appendChild(isolateBtn);
  }

  $detailBody.appendChild(actions);
}

function isolateNodeGraph(nodeId) {
  if (!network) return;
  originalGraphData = {
    nodes: network.body.data.nodes.get(),
    edges: network.body.data.edges.get(),
  };
  isolatedNodeId = nodeId;

  const connectedNodes = new Set([nodeId]);
  const connectedEdges = new Set();
  network.body.data.edges.get().forEach((e) => {
    if (e.from === nodeId || e.to === nodeId) {
      connectedNodes.add(e.from);
      connectedNodes.add(e.to);
      connectedEdges.add(e.id);
    }
  });

  const nds = network.body.data.nodes.get({ filter: (n) => connectedNodes.has(n.id) });
  const eds = network.body.data.edges.get({ filter: (e) => connectedEdges.has(e.id) });

  network.setData({ nodes: new vis.DataSet(nds), edges: new vis.DataSet(eds) });
  network.setOptions({ physics: { solver: "barnesHut", barnesHut: {
    gravitationalConstant: -12000, centralGravity: 0.1, springLength: 250,
    springConstant: 0.02, damping: 0.1, avoidOverlap: 0.5,
  }, stabilization: { iterations: 180 }, maxVelocity: 4, minVelocity: 0.3 } });

  const detailNode = document.getElementById("detail");
  if (detailNode) renderIsolateActions(nodesById.get(nodeId));
  log("vista aislada: " + nds.length + " nodos  " + eds.length + " relaciones", "ok");
  setTimeout(() => network.fit({ animation: { duration: 400, easingFunction: "easeInOutQuad" } }), 300);
}

function restoreFullGraph() {
  if (!network || !originalGraphData) return;
  isolatedNodeId = null;

  network.setData({
    nodes: new vis.DataSet(originalGraphData.nodes),
    edges: new vis.DataSet(originalGraphData.edges),
  });

  network.setOptions({ physics: physicsOptions(originalGraphData.nodes.length) });
  const old = document.getElementById("isolate-actions");
  if (old) old.remove();
  setTimeout(() => network.fit({ animation: { duration: 600, easingFunction: "easeInOutQuad" } }), 400);
  log(" grafo completo restaurado", "ok");
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
      "Sustituye el ID del recurso por otro valor (p.ej. 1 → 9999) y comprueba " +
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
        color: { color: CONF_COLORS[conf] || "#888", highlight: "#4f8cff" },
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
    rerenderLayout();
  });
});

$("#layout-reset").onclick = () => {
  setPreset("balanced");
};

$("#btn-fit").onclick = () => {
  if (network) network.fit({ animation: { duration: 600, easingFunction: "easeInOutQuad" } });
};

function buildNodeTypeFilters() {
  const container = $("#node-type-filters");
  if (!container) return;
  const kinds = Object.keys(NODE_COLORS);
  container.innerHTML = kinds.map((k) => {
    const c = NODE_COLORS[k];
    const checked = NODE_TYPES_VISIBLE[k] !== false;
    return `<label class="ntf-toggle ${checked ? "on" : ""}" data-kind="${k}" style="--ntf-color:${c.bg};--ntf-border:${c.border}">
      <span class="ntf-icon">${c.icon}</span> ${k}
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

document.addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA" || e.target.tagName === "SELECT") return;
  if (e.key === "f" || e.key === "F") {
    e.preventDefault();
    if (network) network.fit({ animation: { duration: 500, easingFunction: "easeInOutQuad" } });
  }
  if (e.key === "Escape") {
    closeDetail();
  }
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