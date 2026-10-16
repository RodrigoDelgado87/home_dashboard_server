"use strict";

const SYSTEM_INTERVAL = 2000;
const APPS_INTERVAL = 10000;
const RING_LEN = 2 * Math.PI * 42;

const $ = (sel) => document.querySelector(sel);
const state = {
  apps: [],
  appsJson: "",
  showHidden: readPref("showHidden") === "1",
  editing: null, // null = novo link; senão o objeto do app
};

function readPref(key) {
  try { return localStorage.getItem("homedash." + key); } catch { return null; }
}
function writePref(key, value) {
  try { localStorage.setItem("homedash." + key, value); } catch { /* ignora */ }
}

// ---------- formatação ----------
function fmtBytes(b, dec = 1) {
  if (b == null || isNaN(b)) return "–";
  const units = ["B", "KB", "MB", "GB", "TB", "PB"];
  let i = 0;
  while (b >= 1024 && i < units.length - 1) { b /= 1024; i++; }
  return `${b.toFixed(i === 0 ? 0 : dec)} ${units[i]}`;
}
const fmtRate = (b) => (b == null ? "–" : fmtBytes(b) + "/s");

function fmtUptime(sec) {
  if (!sec) return "–";
  const d = Math.floor(sec / 86400);
  const h = Math.floor((sec % 86400) / 3600);
  const m = Math.floor((sec % 3600) / 60);
  if (d) return `${d}d ${h}h`;
  if (h) return `${h}h ${m}m`;
  return `${m}m`;
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function level(pct, warn = 70, crit = 90) {
  return pct >= crit ? "crit" : pct >= warn ? "warn" : "";
}

// ---------- componentes ----------
function setRing(id, pct, label, lvl) {
  const el = document.getElementById(id);
  const clamped = Math.max(0, Math.min(100, pct || 0));
  el.querySelector(".value").style.strokeDashoffset = RING_LEN * (1 - clamped / 100);
  el.querySelector(".ring-label").textContent = label;
  el.classList.remove("warn", "crit");
  if (lvl) el.classList.add(lvl);
}

function setBar(el, pct) {
  el.style.width = `${Math.max(0, Math.min(100, pct || 0))}%`;
  el.className = level(pct, 75, 90);
}

function sparkline(id, series, max) {
  const svg = document.getElementById(id);
  const w = 100, h = 32;
  const values = series.flat().filter((v) => v != null);
  const top = max ?? Math.max(1, ...values) * 1.1;
  svg.innerHTML = series.map((s, i) => {
    if (s.length < 2) return "";
    const pts = s.map((v, j) => `${((j / (s.length - 1)) * w).toFixed(2)},${(h - ((v ?? 0) / top) * h).toFixed(2)}`);
    return `<path class="area s${i}" d="M0,${h} L${pts.join(" L")} L${w},${h} Z"/><polyline class="line s${i}" points="${pts.join(" ")}"/>`;
  }).join("");
}

// ---------- métricas ----------
function renderSystem(d) {
  if (!d.cpu) return;
  const host = d.host;
  $("#hostname").textContent = host.hostname;
  $("#host-sub").textContent = `${host.os} · kernel ${host.kernel} · ${host.arch}`;
  $("#uptime").textContent = fmtUptime(host.uptime);
  document.title = `${host.hostname} · HomeDash`;

  // CPU
  const cpu = d.cpu;
  setRing("cpu-ring", cpu.percent, `${Math.round(cpu.percent)}%`, level(cpu.percent));
  $("#cpu-model").textContent = cpu.model || "";
  $("#cpu-model").title = cpu.model || "";
  $("#cpu-cores").textContent = cpu.cores && cpu.cores !== cpu.threads ? `${cpu.cores}C / ${cpu.threads}T` : `${cpu.threads}`;
  $("#cpu-freq").textContent = cpu.freq_mhz ? `${(cpu.freq_mhz / 1000).toFixed(2)} GHz` : "–";
  $("#cpu-load").textContent = cpu.load.map((l) => l.toFixed(2)).join(" · ");
  const bars = $("#cpu-cores-bars");
  if (bars.children.length !== cpu.per_core.length) {
    bars.innerHTML = cpu.per_core.map((_, i) => `<span title="Núcleo ${i}"><i></i></span>`).join("");
  }
  cpu.per_core.forEach((p, i) => {
    const bar = bars.children[i].firstElementChild;
    bar.style.height = `${p}%`;
    bars.children[i].title = `Núcleo ${i}: ${p.toFixed(0)}%`;
  });
  sparkline("cpu-spark", [d.history.cpu], 100);

  // Temperatura
  const t = d.temperature;
  if (t) {
    const crit = t.critical && t.critical > 50 ? t.critical : 100;
    const high = t.high && t.high > 40 ? t.high : crit * 0.85;
    const lvl = t.current >= crit * 0.95 ? "crit" : t.current >= high * 0.9 ? "warn" : "";
    setRing("temp-ring", (t.current / crit) * 100, `${Math.round(t.current)}°C`, lvl);
    $("#temp-source").textContent = t.source;
  } else {
    setRing("temp-ring", 0, "N/D", "");
    $("#temp-source").textContent = "sensor não encontrado";
  }
  $("#sensors").innerHTML = d.sensors.length
    ? d.sensors.map((s) => `<li><span title="${escapeHtml(s.chip)}">${escapeHtml(s.label)}</span><span>${s.current.toFixed(0)}°C</span></li>`).join("")
    : `<li><span>Nenhum sensor exposto. Veja o README (lm-sensors).</span></li>`;
  sparkline("temp-spark", [d.history.temp], 100);

  // Memória
  const mem = d.memory;
  setRing("mem-ring", mem.percent, `${Math.round(mem.percent)}%`, level(mem.percent, 75, 90));
  $("#mem-total").textContent = `${fmtBytes(mem.total)} total`;
  $("#mem-used").textContent = fmtBytes(mem.used);
  $("#mem-avail").textContent = fmtBytes(mem.available);
  $("#mem-cache").textContent = fmtBytes(mem.cached);
  if (d.swap.total) {
    setBar($("#swap-bar"), d.swap.percent);
    $("#swap-text").textContent = `${fmtBytes(d.swap.used)} / ${fmtBytes(d.swap.total)}`;
  } else {
    setBar($("#swap-bar"), 0);
    $("#swap-text").textContent = "desativado";
  }
  sparkline("mem-spark", [d.history.mem], 100);

  // Rede e disco
  $("#net-rx").textContent = fmtRate(d.network.rx_rate);
  $("#net-tx").textContent = fmtRate(d.network.tx_rate);
  $("#net-ifaces").textContent = d.network.interfaces.map((i) => i.name).join(", ");
  $("#io-read").textContent = fmtRate(d.disk_io.read_rate);
  $("#io-write").textContent = fmtRate(d.disk_io.write_rate);
  sparkline("net-spark", [d.history.rx, d.history.tx]);

  // Discos
  $("#disks").innerHTML = d.disks.length
    ? d.disks.map((k) => `
      <li>
        <div class="disk-head">
          <strong title="${escapeHtml(k.device)}">${escapeHtml(k.mountpoint)}</strong>
          <span class="muted small">${escapeHtml(k.fstype)} · ${fmtBytes(k.used)} / ${fmtBytes(k.total)} (${k.percent.toFixed(0)}%)</span>
        </div>
        <div class="bar"><span class="${level(k.percent, 75, 90)}" style="width:${k.percent}%"></span></div>
      </li>`).join("")
    : `<li class="muted">Nenhum disco encontrado.</li>`;
}

async function pollSystem() {
  try {
    const res = await fetch("api/system", { cache: "no-store" });
    if (!res.ok) throw new Error(res.status);
    renderSystem(await res.json());
    $("#conn").className = "conn on";
  } catch (err) {
    $("#conn").className = "conn off";
    $("#host-sub").textContent = "Sem conexão com o servidor…";
  } finally {
    setTimeout(pollSystem, SYSTEM_INTERVAL);
  }
}

// ---------- aplicações ----------
const ICONS = {
  edit: `<svg viewBox="0 0 24 24"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>`,
  hide: `<svg viewBox="0 0 24 24"><path d="M9.9 4.2A10 10 0 0 1 12 4c6.5 0 10 8 10 8a17 17 0 0 1-2.2 3.2M6.6 6.6A17 17 0 0 0 2 12s3.5 8 10 8a9.7 9.7 0 0 0 5.4-1.6"/><path d="m2 2 20 20"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/></svg>`,
  show: `<svg viewBox="0 0 24 24"><path d="M2 12s3.5-8 10-8 10 8 10 8-3.5 8-10 8-10-8-10-8Z"/><circle cx="12" cy="12" r="3"/></svg>`,
};

function appUrl(a) {
  if (a.url) return a.url;
  if (!a.port) return null;
  return `${a.scheme || "http"}://${location.hostname}:${a.port}${a.path || ""}`;
}

function letterColor(name) {
  let h = 0;
  for (const c of name) h = (h * 31 + c.charCodeAt(0)) % 360;
  return `hsl(${h} 55% 42%)`;
}

function letterHtml(name) {
  return `<span class="letter" style="background:${letterColor(name)}">${escapeHtml((name || "?").charAt(0).toUpperCase())}</span>`;
}

function tileHtml(a) {
  const url = appUrl(a);
  const icon = a.icon_url
    ? `<img src="${escapeHtml(a.icon_url)}" alt="" loading="lazy" data-name="${escapeHtml(a.name)}">`
    : letterHtml(a.name);
  const meta = a.container
    ? `<span class="dot ${escapeHtml(a.state)}"></span>${a.port ? ":" + a.port : escapeHtml(a.state)}`
    : `<span class="dot running"></span>link`;
  const tag = url ? "a" : "div";
  const href = url ? ` href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer"` : "";
  const classes = ["app-tile", a.hidden && "is-hidden", a.container && a.state !== "running" && "stopped"].filter(Boolean).join(" ");
  const title = a.container ? `${a.image}\n${a.status || ""}` : a.url;
  return `
    <div class="${classes}" data-key="${escapeHtml(a.key)}">
      <${tag} class="app-link"${href} title="${escapeHtml(title)}">
        <div class="app-icon">${icon}</div>
        <div class="app-name">${escapeHtml(a.name)}</div>
        <div class="app-meta">${meta}</div>
      </${tag}>
      <div class="app-actions">
        <button class="icon-btn" data-act="edit" title="Editar">${ICONS.edit}</button>
        <button class="icon-btn" data-act="toggle" title="${a.hidden ? "Mostrar" : "Ocultar"}">${a.hidden ? ICONS.show : ICONS.hide}</button>
      </div>
    </div>`;
}

function renderApps() {
  const visible = state.apps.filter((a) => state.showHidden || !a.hidden);
  const web = visible.filter((a) => a.has_web);
  const others = visible.filter((a) => !a.has_web);
  $("#apps").innerHTML = web.length
    ? web.map(tileHtml).join("")
    : `<p class="empty">Nenhuma aplicação com interface web encontrada.</p>`;
  $("#others").innerHTML = others.map(tileHtml).join("");
  $("#others-wrap").hidden = others.length === 0;
  $("#others-count").textContent = `(${others.length})`;
}

async function loadApps(force = false) {
  try {
    const res = await fetch("api/apps", { cache: "no-store" });
    if (!res.ok) throw new Error(res.status);
    const data = await res.json();
    const err = $("#docker-error");
    err.hidden = !data.docker_error;
    err.textContent = data.docker_error || "";
    const json = JSON.stringify(data.apps);
    if (force || json !== state.appsJson) {
      state.appsJson = json;
      state.apps = data.apps;
      renderApps();
    }
  } catch { /* tenta de novo no próximo ciclo */ }
}

async function api(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let msg = `Erro ${res.status}`;
    try { msg = (await res.json()).detail || msg; } catch { /* ignora */ }
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return res.json();
}

const findApp = (key) => state.apps.find((a) => a.key === key);

function openEditor(app) {
  state.editing = app;
  const isNew = !app;
  const ov = app?.overrides || {};
  $("#edit-title").textContent = isNew ? "Adicionar link" : `Editar ${app.name}`;
  if (isNew || !app.container) {
    $("#f-name").value = app?.name || "";
    $("#f-url").value = app?.url || "";
    $("#f-icon").value = ov.icon || "";
    $("#f-name").placeholder = "Meu roteador";
    $("#f-url").placeholder = "http://192.168.0.1";
    $("#f-icon").placeholder = "ex.: openwrt";
    $("#f-name").required = $("#f-url").required = true;
  } else {
    $("#f-name").value = ov.name || "";
    $("#f-url").value = ov.url || "";
    $("#f-icon").value = ov.icon || "";
    $("#f-name").placeholder = app.auto_name;
    $("#f-url").placeholder = (app.auto_url || (app.port ? `${app.scheme}://${location.hostname}:${app.port}${app.path || ""}` : "nenhuma porta detectada"));
    $("#f-icon").placeholder = app.auto_icon;
    $("#f-name").required = $("#f-url").required = false;
  }
  $("#edit-hint").textContent = isNew
    ? "Ícones: procure o nome em github.com/homarr-labs/dashboard-icons."
    : app.container
      ? `Container ${app.key} · ${app.image}. Deixe vazio para usar o valor detectado.`
      : "Link adicionado manualmente.";
  const reset = $("#edit-reset");
  reset.hidden = isNew;
  reset.textContent = app && !app.container ? "Excluir" : "Restaurar padrão";
  $("#edit-dialog").showModal();
}

async function saveEditor(ev) {
  ev.preventDefault();
  const body = { name: $("#f-name").value.trim(), url: $("#f-url").value.trim(), icon: $("#f-icon").value.trim() };
  try {
    if (!state.editing) {
      await api("POST", "api/custom", { ...body, icon: body.icon || null });
    } else {
      await api("PATCH", `api/apps/${encodeURIComponent(state.editing.key)}`, body);
    }
    $("#edit-dialog").close();
    loadApps(true);
  } catch (err) {
    alert(err.message);
  }
}

async function resetEditor() {
  const app = state.editing;
  if (!app) return;
  const msg = app.container
    ? `Restaurar ${app.name} para a configuração detectada automaticamente?`
    : `Excluir o link ${app.name}?`;
  if (!confirm(msg)) return;
  try {
    await api("DELETE", `api/apps/${encodeURIComponent(app.key)}`);
    $("#edit-dialog").close();
    loadApps(true);
  } catch (err) {
    alert(err.message);
  }
}

async function onTileClick(ev) {
  const btn = ev.target.closest("button[data-act]");
  if (!btn) return;
  ev.preventDefault();
  const app = findApp(btn.closest(".app-tile").dataset.key);
  if (!app) return;
  if (btn.dataset.act === "edit") return openEditor(app);
  if (btn.dataset.act === "toggle") {
    try {
      await api("PATCH", `api/apps/${encodeURIComponent(app.key)}`, { hidden: !app.hidden });
      loadApps(true);
    } catch (err) {
      alert(err.message);
    }
  }
}

// ---------- inicialização ----------
// ícone que falhou ao carregar vira avatar com a inicial
document.addEventListener("error", (ev) => {
  const img = ev.target;
  if (img.tagName === "IMG" && img.closest(".app-icon")) {
    img.outerHTML = letterHtml(img.dataset.name);
  }
}, true);

$("#show-hidden").checked = state.showHidden;
$("#show-hidden").addEventListener("change", (ev) => {
  state.showHidden = ev.target.checked;
  writePref("showHidden", state.showHidden ? "1" : "0");
  renderApps();
});
$("#add-link").addEventListener("click", () => openEditor(null));
$("#edit-form").addEventListener("submit", saveEditor);
$("#edit-cancel").addEventListener("click", () => $("#edit-dialog").close());
$("#edit-reset").addEventListener("click", resetEditor);
$("#apps").addEventListener("click", onTileClick);
$("#others").addEventListener("click", onTileClick);

pollSystem();
loadApps();
setInterval(loadApps, APPS_INTERVAL);
