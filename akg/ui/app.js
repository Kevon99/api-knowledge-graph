const API = "/api/v1";

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
  const { ok, body } = await api("/graph/summary");
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
  Host: "#4c72b0",
  Endpoint: "#55a868",
  Token: "#c44e52",
  Cookie: "#8172b2",
  Session: "#ccb974",
  Resource: "#64b5cd",
  Flow: "#dd8452",
  AuthFlow: "#ff9f43",
  Exchange: "#999999",
};

const CONF_COLORS = { EVIDENCIA: "#3fb68b", INFERENCIA: "#ffc857" }; // edge por confianza

// ── Ajustes de layout (persistidos en localStorage) ─────────────────────
const LAYOUT_DEFAULTS = {
  spring: 260,          // separacion entre nodos conectados
  repulsion: 32000,     // repulsion entre todos los nodos
  overlap: 0.6,         // 0..1 evitar superposicion
  size: 16,             // tamano de nodo
  font: 11,             // tamano de fuente
};
let layout = { ...LAYOUT_DEFAULTS };
try {
  const saved = JSON.parse(localStorage.getItem("akg-layout"));
  if (saved) layout = { ...LAYOUT_DEFAULTS, ...saved };
} catch (_) { /* layout por defecto */ }

function saveLayout() {
  try { localStorage.setItem("akg-layout", JSON.stringify(layout)); } catch (_) {}
}

function physicsOptions() {
  return {
    enabled: true,
    solver: "barnesHut",
    barnesHut: {
      gravitationalConstant: -layout.repulsion,
      centralGravity: 0.05,
      springLength: layout.spring,
      springConstant: 0.02,
      damping: 0.1,
      avoidOverlap: layout.overlap,
    },
    stabilization: { iterations: 500, updateInterval: 25 },
    minVelocity: 0.3,
  };
}

function nodeKey(nd) {
  // identidad estable a partir de las propiedades del nodo
  if (!nd) return "?";
  const keys = Object.keys(nd).sort();
  return keys.map((k) => `${k}=${String(nd[k]).slice(0, 40)}`).join("|");
}

function nodeLabel(nd) {
  const host = nd.host || nd.name || "";
  const path = nd.pattern || nd.path || "";
  const method = nd.method || "";
  const label = (method ? method + " " : "") + (host + (path ? " " + path : "")).trim() || "?";
  return label.slice(0, 26);
}

const AUTH_SIGNAL_COLORS = {
  token: { background: "#4f8cff", border: "#1c5cb8" },
  cookie: { background: "#ffc857", border: "#b8871c" },
};

async function highlightAuthEndpoints(nodes) {
  try {
    const { ok, body } = await api("/graph/auth-endpoints");
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
    if (updates.length && network) network.body.data.nodes.update(updates);
  } catch (_) { /* sin marcado */ }
}

function renderGraph(nodes, edges, cypherType) {
  if (network) { network.destroy(); network = null; }
  graphEl.innerHTML = "";
  if (!nodes.length) {
    graphEl.innerHTML = "<div class='hint'>sin nodos para mostrar</div>";
    return;
  }
  const data = { nodes: new vis.DataSet(nodes), edges: new vis.DataSet(edges) };
  const opts = {
    nodes: {
      shape: "dot",
      size: layout.size,
      scaling: { min: 12, max: 34 },
      font: { size: layout.font },
      borderWidth: 1,
    },
    edges: {
      arrows: "to",
      smooth: { type: "continuous" },
      width: 1.2,
      font: { size: 9, align: "middle", color: "#666" },
    },
    interaction: { hover: true, hoverConnectedEdges: true },
    physics: physicsOptions(),
  };
  network = new vis.Network(graphEl, data, opts);
  window.__network = network; // debug: inspeccionar nodos coloreados
  network.on("click", (params) => {
    const { nodes: clicked } = params;
    if (clicked && clicked.length) showDetail(nodesById.get(clicked[0]));
  });
  network.on("hoverNode", (params) => focusOnNode(params.node));
  network.on("blurNode", () => clearFocus());
  lastGraph = { nodes, edges, cypherType };
  log(`grafo: ${nodes.length} nodos · ${edges.length} relaciones (${cypherType || "?"})`, "ok");
}

// ── Foco al pasar el mouse: ilumina conexiones directas y atenúa el resto ──
let focusTimer = null;

function focusOnNode(nodeId) {
  if (!network) return;
  clearTimeout(focusTimer);
  const nodeDS = network.body.data.nodes;
  const edgeDS = network.body.data.edges;
  const connected = new Set([nodeId]);
  const edgeUpdates = [];
  edgeDS.get().forEach((e) => {
    const isConn = e.from === nodeId || e.to === nodeId;
    if (isConn) {
      connected.add(e.from);
      connected.add(e.to);
    }
    edgeUpdates.push({ id: e.id, opacity: isConn ? 1 : 0.07 });
  });
  nodeDS.update(
    nodeDS.get().map((n) => ({ id: n.id, opacity: connected.has(n.id) ? 1 : 0.15 }))
  );
  edgeDS.update(edgeUpdates);
}

function clearFocus() {
  if (!network) return;
  focusTimer = setTimeout(() => {
    const nodeDS = network.body.data.nodes;
    const edgeDS = network.body.data.edges;
    nodeDS.get().forEach((n) => nodeDS.update({ id: n.id, opacity: 1 }));
    edgeDS.get().forEach((e) => edgeDS.update({ id: e.id, opacity: 1 }));
  }, 80);
}

// ultimo grafo renderizado para re-render al cambiar el layout
let lastGraph = null;
let layoutTimer = null;

function rerenderLayout() {
  saveLayout();
  if (!lastGraph) return;
  clearTimeout(layoutTimer);
  layoutTimer = setTimeout(() => {
    renderGraph(lastGraph.nodes, lastGraph.edges, lastGraph.cypherType);
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
  const raw = d.raw_request || "";
  $("#detail-title").textContent = `Request · ${d.method} ${d.host}`;
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

  const curlBtn = document.createElement("button");
  curlBtn.className = "req-btn curl";
  curlBtn.textContent = "Copiar como cURL";
  curlBtn.onclick = () => copyCurl(d);
  container.appendChild(curlBtn);

  $detailBody.innerHTML = "";
  $detailBody.appendChild(container);
  $detail.classList.remove("hidden");
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
  const { ok, body } = await api("/graph/auth-flow");
  if (!ok) { log("no hay flujos de autenticacion", "err"); return; }
  buildGraphFromViews(body, "auth-flow");
}

async function loadResources() {
  const { ok, body } = await api("/graph/resources");
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
  const lines = [
    `# ${body.title}`,
    `regla: ${body.rule_id} · severidad: ${body.severity} · estado: ${body.status}`,
    `confianza: ${body.confidence ?? "—"}`,
    "",
    "## Detalle",
    body.description || "—",
    "",
    "## Evidencia",
    ...Object.entries(fields).map(([k, v]) => `${k}: ${escapeHtml(String(v))}`),
    "",
    `## Exchanges implicados (${body.exchange_ids.length})`,
    ...(body.exchange_ids.map((id) => id).join("\n") || "sin exchanges resueltos"),
    "",
    "## Nodos",
    (body.node_keys || []).join("\n") || "—",
  ].join("\n");
  $("#detail-title").textContent = `Finding ${body.severity}`;
  $("#detail-body").textContent = lines;
  $("#detail").classList.remove("hidden");
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
      color: { background: NODE_COLORS[lab] || "#888", border: "#333" },
      props: nd.properties,
    };
    nodesById.set(node.id, node);
    return node;
  });
  const edges = (body.edges || []).map((e) => ({
    from: e.source,
    to: e.target,
    label: e.type.slice(0, 10),
    arrows: "to",
  }));
  renderGraph(nodes, edges, kind);
  highlightAuthEndpoints(nodes); // fire-and-forget; pinta tras resolver
}

async function runQuery() {
  nodesById.clear();
  const label = $("#node-label").value.trim().replace(/[^a-zA-Z0-9_]/g, "");
  const limit = $("#node-limit") ? $("#node-limit").value : 80;
  // Grafo semantico por defecto: hosts, endpoints, tokens, cookies, sesiones y flujos.
  // Se excluyen Exchange (evidencia) y el ruido de cookies por exchange para que la
  // vista muestre conocimiento navegable, no trafico crudo.
  const cypher = label
    ? `MATCH (n:\`${label}\`)-[rel*0..1]->(m) RETURN n, rel, m, labels(n) AS nlabels, labels(m) AS mlabels LIMIT ${Number(limit) || 80}`
    : `MATCH (a)-[r]->(b) WHERE NOT a:Exchange AND NOT b:Exchange ` +
      `AND type(r) <> 'SENDS' AND type(r) <> 'RECEIVES' ` +
      `RETURN a, r, b, properties(r) AS rprops, labels(a) AS alabels, labels(b) AS blabels LIMIT ${Number(limit) || 80}`;
  const { ok, body } = await api("/graph/query", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ cypher }),
  });
  if (!ok) { log(`consulta rechazada: ${body.detail}`, "err"); return; }

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
        color: { background: NODE_COLORS[lab] || "#888", border: "#333" },
        props: nd,
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
  renderGraph(nodes, edges, label || "semantico");
  highlightAuthEndpoints(nodes); // pinta en azul los endpoints que usan auth
}

// ── wiring ──────────────────────────────────────────────────────────────
$("#btn-new-ws").onclick = createWorkspace;
$("#btn-upload").onclick = () => $("#file-input").click();
$("#file-input").onchange = (e) => e.target.files[0] && uploadFile(e.target.files[0]);
$("#btn-query").onclick = runQuery;
$("#node-label").addEventListener("keydown", (e) => e.key === "Enter" && runQuery());
$("#ws-select").addEventListener("change", () => { loadSummary(); runQuery(); });
$("#detail-close").onclick = closeDetail;

// ── controles de layout ─────────────────────────────────────────────────
const LAYOUT_SLIDERS = {
  spring: { el: "#adj-spring", v: "#adj-spring-v", fmt: (v) => v + " px" },
  repulsion: { el: "#adj-repulsion", v: "#adj-repulsion-v", fmt: (v) => v.toLocaleString("es") },
  overlap: { el: "#adj-overlap", v: "#adj-overlap-v", fmt: (v) => (v * 100).toFixed(0) + "%" },
  size: { el: "#adj-size", v: "#adj-size-v", fmt: (v) => v + " px" },
  font: { el: "#adj-font", v: "#adj-font-v", fmt: (v) => v + " px" },
};

function syncLayoutControls() {
  Object.entries(LAYOUT_SLIDERS).forEach(([key, cfg]) => {
    const slider = $(cfg.el);
    if (!slider) return;
    slider.value = layout[key];
    $(cfg.v).textContent = cfg.fmt(layout[key]);
  });
}

Object.entries(LAYOUT_SLIDERS).forEach(([key, cfg]) => {
  const slider = $(cfg.el);
  if (!slider) return;
  slider.addEventListener("input", () => {
    layout[key] = cfg.el === "#adj-overlap" ? Number(slider.value) / 100 : Number(slider.value);
    $(cfg.v).textContent = cfg.fmt(layout[key]);
    rerenderLayout();
  });
});

$("#layout-reset").onclick = () => {
  layout = { ...LAYOUT_DEFAULTS };
  syncLayoutControls();
  rerenderLayout();
};
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
  await loadWorkspaces();
})();