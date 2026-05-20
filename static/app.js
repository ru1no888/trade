const $ = (id) => document.getElementById(id);
const logBox = $("log");
const canvas = $("chartCanvas");
const ctx = canvas.getContext("2d");

let lastPayload = null;
let currentConfig = {};
let liveTimer = null;
let lastHeavyRefreshAt = 0;

function log(msg, obj = null) {
  logBox.textContent = obj ? `${msg}\n${JSON.stringify(obj, null, 2)}` : msg;
}

async function api(path, options = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  const text = await res.text();
  let data;
  try { data = JSON.parse(text); } catch { data = text; }
  if (!res.ok) throw new Error(data.detail || data);
  return data;
}

function money(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n.toFixed(2) : "-";
}

function price(v) {
  const n = Number(v);
  if (!Number.isFinite(n)) return "-";
  return Math.abs(n) >= 100 ? n.toFixed(2) : n.toFixed(5);
}

function delayText(seconds) {
  const n = Number(seconds);
  if (!Number.isFinite(n)) return "delay ?";
  if (n < 60) return `delay ${n}s`;
  return `delay ${Math.floor(n / 60)}m ${n % 60}s`;
}

function fillSelect(id, rows) {
  const el = $(id);
  el.innerHTML = "";
  for (const row of rows) {
    const option = document.createElement("option");
    option.value = row.id;
    option.textContent = row.name;
    el.appendChild(option);
  }
}

function selectedPreset(rows, id) {
  return rows.find((row) => row.id === $(id).value) || rows[0];
}

function fillConfig(cfg) {
  currentConfig = cfg;
  const form = $("configForm");
  for (const [k, v] of Object.entries(cfg)) {
    const el = form.elements[k];
    if (!el) continue;
    if (el.type === "checkbox") el.checked = !!v;
    else el.value = v;
  }
  $("autoBadge").textContent = cfg.auto_enabled ? "AUTO: ON" : "AUTO: OFF";
  $("autoBadge").classList.toggle("on", !!cfg.auto_enabled);
}

function readConfigForm() {
  const form = $("configForm");
  const payload = {};
  for (const el of form.elements) {
    if (!el.name) continue;
    if (el.type === "checkbox") payload[el.name] = el.checked;
    else if (el.type === "number") payload[el.name] = Number(el.value);
    else payload[el.name] = el.value;
  }
  return payload;
}

async function saveConfig(extra = {}) {
  const payload = { ...readConfigForm(), ...extra };
  const data = await api("/api/config", { method: "POST", body: JSON.stringify(payload) });
  fillConfig(data.config);
  return data.config;
}

function updateSignal(signal) {
  const box = $("signalText");
  const sideLabel = signal?.signal === "BUY" ? "BUY ซื้อขึ้น" : signal?.signal === "SELL" ? "SELL ขายลง" : "WAIT";
  box.textContent = sideLabel;
  box.className = "signal " + String(signal?.signal || "wait").toLowerCase();
  $("closeVal").textContent = price(signal?.close);
  $("probVal").textContent = signal?.probability_up ?? "-";
  $("rsiVal").textContent = signal?.rsi_14 ?? "-";
  $("newsVal").textContent = signal?.news_sentiment ?? "-";
  $("reasonText").textContent = signal?.reason?.join(" | ") || "-";
}

function updateScan(data) {
  $("scanStatus").textContent = `สแกน ${data.rows?.length || 0} ตัว`;
  $("bestDownBox").textContent = data.best_down
    ? `ตัวน่าลง: ${data.best_down.symbol} | ลง ${(Number(data.best_down.probability_down) * 100).toFixed(1)}% | ข่าว ${data.best_down.news_sentiment}`
    : "ยังไม่มีตัวน่าลง";

  const body = $("scanBody");
  body.innerHTML = "";
  for (const row of data.rows || []) {
    const suggested = row.suggested_side === "BUY" ? "ซื้อขึ้น" : row.suggested_side === "SELL" ? "ขายลง" : "รอ";
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${row.symbol}</td>
      <td>${row.signal}</td>
      <td>${suggested}</td>
      <td>${row.news_sentiment}</td>
      <td>${(Number(row.probability_down) * 100).toFixed(1)}%</td>
      <td>${price(row.close)}</td>
      <td>${row.news_query || ""}</td>
      <td>${(row.reason || []).join(" | ")}</td>
    `;
    body.appendChild(tr);
  }
}

function updateNews(data) {
  const box = $("newsBox");
  if (!box) return;
  const rows = data.rows || [];
  if (!rows.length) {
    box.textContent = "ข่าว: ไม่มีข้อมูล";
    return;
  }
  box.innerHTML = rows.map((row) => {
    const headlines = (row.headlines || []).slice(0, 3).map((title) => `<li>${title}</li>`).join("");
    const bias = row.bias === "negative" ? "ลบ" : row.bias === "positive" ? "บวก" : "กลาง";
    return `
      <div class="news-item">
        <b>${row.symbol}</b> ข่าว ${bias} (${row.sentiment})
        <small>ค้น: ${row.query}</small>
        <ul>${headlines || "<li>ไม่พบ headline</li>"}</ul>
      </div>
    `;
  }).join("");
}

function updateState(state) {
  const unrealized = Number(state?.unrealized_pnl ?? 0);
  $("balanceVal").textContent = money(state?.balance);
  $("equityVal").textContent = money(state?.equity ?? state?.balance);
  $("unrealizedVal").textContent = money(unrealized);
  $("unrealizedVal").className = unrealized >= 0 ? "pnl-good" : "pnl-bad";
  $("currentPriceVal").textContent = price(state?.current_price);

  const closedCount = state?.trades?.length ?? 0;
  const openCount = state?.open_position ? 1 : 0;
  $("tradeCountVal").textContent = `${closedCount + openCount} (${openCount} open)`;

  if (state?.open_position) {
    const p = state.open_position;
    const side = p.side === "BUY" ? "BUY ซื้อขึ้น" : "SELL ขายลง";
    $("positionBox").textContent =
      `OPEN ${side}\nEntry: ${price(p.entry)}\nNow: ${price(state.current_price)}\nPnL: ${money(unrealized)}\nSL: ${price(p.stop_loss)}\nTP: ${price(p.take_profit)}\nRisk: ${money(p.risk_amount)}\nLot~ ${p.approx_lot}\nOpened: ${p.opened_at}`;
  } else {
    $("positionBox").textContent = "ไม่มีไม้เปิด";
  }

  const body = $("tradeBody");
  body.innerHTML = "";
  const trades = [...(state?.trades || [])].reverse().slice(0, 60);
  for (const t of trades) {
    const tr = document.createElement("tr");
    const pnlClass = Number(t.pnl) >= 0 ? "pnl-good" : "pnl-bad";
    tr.innerHTML = `
      <td>${t.opened_at || ""}</td>
      <td>${t.side === "BUY" ? "ซื้อขึ้น" : t.side === "SELL" ? "ขายลง" : ""}</td>
      <td>${price(t.entry)}</td>
      <td>${price(t.stop_loss)}</td>
      <td>${price(t.take_profit)}</td>
      <td>${price(t.exit)}</td>
      <td>${t.close_reason || ""}</td>
      <td class="${pnlClass}">${money(t.pnl)}</td>
      <td>${money(t.balance_after)}</td>
    `;
    body.appendChild(tr);
  }
}

function drawChart(candles, state = null) {
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth;
  const h = 520;
  canvas.width = Math.floor(w * dpr);
  canvas.height = Math.floor(h * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = "#07111f";
  ctx.fillRect(0, 0, w, h);

  if (!candles || candles.length < 5) {
    ctx.fillStyle = "#98a8bd";
    ctx.font = "15px system-ui";
    ctx.fillText("ยังไม่มีกราฟ", 24, 36);
    return;
  }

  const pad = { l: 58, r: 22, t: 20, b: 44 };
  const plotW = w - pad.l - pad.r;
  const plotH = h - pad.t - pad.b;
  const values = [];
  candles.forEach(c => values.push(Number(c.high), Number(c.low), Number(c.ema_50), Number(c.ema_200)));
  if (state?.open_position) values.push(Number(state.open_position.entry), Number(state.open_position.stop_loss), Number(state.open_position.take_profit));
  if (state?.current_price) values.push(Number(state.current_price));

  const minP = Math.min(...values);
  const maxP = Math.max(...values);
  const range = maxP - minP || 1;
  const y = (p) => pad.t + (maxP - p) / range * plotH;
  const x = (i) => pad.l + i / (candles.length - 1) * plotW;

  ctx.strokeStyle = "#20304b";
  ctx.lineWidth = 1;
  ctx.fillStyle = "#98a8bd";
  ctx.font = "12px system-ui";
  for (let i = 0; i <= 5; i++) {
    const yy = pad.t + i / 5 * plotH;
    ctx.beginPath();
    ctx.moveTo(pad.l, yy);
    ctx.lineTo(w - pad.r, yy);
    ctx.stroke();
    ctx.fillText(price(maxP - i / 5 * range), 8, yy + 4);
  }

  function line(key, color) {
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    candles.forEach((c, i) => {
      const xx = x(i);
      const yy = y(Number(c[key]));
      if (i === 0) ctx.moveTo(xx, yy);
      else ctx.lineTo(xx, yy);
    });
    ctx.stroke();
  }
  line("ema_50", "#2f9eeb");
  line("ema_200", "#f5c542");

  const candleW = Math.max(3, Math.min(10, plotW / candles.length * 0.65));
  candles.forEach((c, i) => {
    const open = Number(c.open), high = Number(c.high), low = Number(c.low), close = Number(c.close);
    const xx = x(i);
    const up = close >= open;
    const color = up ? "#21b981" : "#e65b5b";
    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(xx, y(high));
    ctx.lineTo(xx, y(low));
    ctx.stroke();
    const top = y(Math.max(open, close));
    const bot = y(Math.min(open, close));
    ctx.fillRect(xx - candleW / 2, top, candleW, Math.max(1, bot - top));
  });

  function drawHLine(value, color, label) {
    const yy = y(Number(value));
    ctx.strokeStyle = color;
    ctx.setLineDash([5, 5]);
    ctx.beginPath();
    ctx.moveTo(pad.l, yy);
    ctx.lineTo(w - pad.r, yy);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = color;
    ctx.fillText(label, pad.l + 8, yy - 6);
  }

  if (state?.open_position) {
    const p = state.open_position;
    drawHLine(p.entry, "#ffffff", `ENTRY ${price(p.entry)}`);
    drawHLine(p.stop_loss, "#e65b5b", `SL ${price(p.stop_loss)}`);
    drawHLine(p.take_profit, "#21b981", `TP ${price(p.take_profit)}`);
  }
  if (state?.current_price) drawHLine(state.current_price, "#f5c542", `NOW ${price(state.current_price)}`);

  ctx.fillStyle = "#2f9eeb"; ctx.fillText("EMA50", pad.l, h - 18);
  ctx.fillStyle = "#f5c542"; ctx.fillText("EMA200", pad.l + 70, h - 18);
}

async function loadConfig() {
  const cfg = await api("/api/config");
  fillConfig(cfg);
}

async function loadPresets() {
  const presets = await api("/api/presets");
  window.presets = presets;
  fillSelect("marketPreset", presets.market_packs);
  fillSelect("timePreset", presets.timeframes);
  fillSelect("riskPreset", presets.risk_modes);
}

async function loadState() {
  const state = await api("/api/state");
  updateState(state);
}

async function loadChart() {
  const data = await api("/api/chart", { method: "POST", body: "{}" });
  lastPayload = { ...(lastPayload || {}), candles: data.candles, chart_symbol: data.chart_symbol };
  $("chartSymbol").textContent = data.chart_symbol;
  $("chartStatus").textContent = `${data.candles.length} bars`;
  drawChart(data.candles, lastPayload?.state || null);
  return data;
}

async function loadLive() {
  const data = await api("/api/live", { method: "POST", body: "{}" });
  lastPayload = data;
  $("chartSymbol").textContent = data.chart_symbol || "-";
  $("chartStatus").textContent = `${data.candles?.length || 0} bars | ${price(data.current_price)} | ${delayText(data.data_delay_seconds)}`;
  updateState(data.state);
  drawChart(data.candles, data.state);
  return data;
}

async function scanMarket() {
  $("scanStatus").textContent = "กำลังสแกน...";
  const data = await api("/api/scan", { method: "POST", body: "{}" });
  updateScan(data);
  return data;
}

async function loadNews() {
  const data = await api("/api/news", { method: "POST", body: "{}" });
  updateNews(data);
  return data;
}

async function reloadStep() {
  const data = await api("/api/reload", { method: "POST", body: "{}" });
  lastPayload = data;
  $("chartSymbol").textContent = data.chart_symbol || "-";
  $("chartStatus").textContent = `${data.candles?.length || 0} bars | ${delayText(data.data_delay_seconds)}`;
  updateSignal(data.signal);
  updateState(data.state);
  drawChart(data.candles, data.state);
  log("บอทคิดเสร็จ", { message: data.message, candle_time: data.candle_time, signal: data.signal.signal });
  return data;
}

async function liveTick() {
  try {
    await loadLive();
    const now = Date.now();
    if (now - lastHeavyRefreshAt > 60000) {
      lastHeavyRefreshAt = now;
      await scanMarket();
      await loadNews();
    }
  } catch (e) {
    log("LIVE ERROR: " + e.message);
  }
}

function restartLiveTimer() {
  if (liveTimer) clearInterval(liveTimer);
  const seconds = Math.max(5, Number(currentConfig.auto_refresh_seconds || 30));
  liveTimer = setInterval(liveTick, seconds * 1000);
}

$("applyPresetBtn").addEventListener("click", async () => {
  try {
    const p = window.presets;
    const market = selectedPreset(p.market_packs, "marketPreset");
    const time = selectedPreset(p.timeframes, "timePreset");
    const risk = selectedPreset(p.risk_modes, "riskPreset");
    const cfg = await saveConfig({ symbol: market.symbols, ...time, ...risk });
    log("ใช้ preset แล้ว", { symbol: cfg.symbol, period: cfg.period, interval: cfg.interval });
    await loadLive();
    await loadNews();
  } catch (e) { log("ERROR: " + e.message); }
});

$("saveBtn").addEventListener("click", async () => {
  try { log("บันทึกแล้ว", await saveConfig()); restartLiveTimer(); }
  catch (e) { log("ERROR: " + e.message); }
});

$("chartBtn").addEventListener("click", async () => {
  try { await saveConfig(); await loadLive(); }
  catch (e) { log("ERROR: " + e.message); }
});

$("trainBtn").addEventListener("click", async () => {
  try {
    await saveConfig();
    log("กำลังเทรน...");
    const data = await api("/api/train", { method: "POST", body: "{}" });
    log("เทรนสำเร็จ", data.metrics);
    await scanMarket();
    await loadNews();
  } catch (e) { log("ERROR: " + e.message); }
});

$("reloadBtn").addEventListener("click", async () => {
  try { await saveConfig(); await reloadStep(); }
  catch (e) { log("ERROR: " + e.message); }
});

$("scanBtn").addEventListener("click", async () => {
  try { await saveConfig(); await scanMarket(); await loadNews(); }
  catch (e) { log("ERROR: " + e.message); }
});

$("startBtn").addEventListener("click", async () => {
  try {
    await saveConfig();
    const data = await api("/api/start", { method: "POST", body: "{}" });
    await loadConfig();
    restartLiveTimer();
    await loadLive();
    log("เปิด Auto แล้ว", data);
  } catch (e) { log("ERROR: " + e.message); }
});

$("stopBtn").addEventListener("click", async () => {
  try {
    const data = await api("/api/stop", { method: "POST", body: "{}" });
    await loadConfig();
    restartLiveTimer();
    await loadLive();
    log("หยุด Auto แล้ว", data);
  } catch (e) { log("ERROR: " + e.message); }
});

$("resetBtn").addEventListener("click", async () => {
  try {
    const data = await api("/api/reset", { method: "POST", body: "{}" });
    lastPayload = { ...(lastPayload || {}), state: data.state };
    updateState(data.state);
    drawChart(lastPayload?.candles || [], data.state);
    log("รีเซ็ตแล้ว", data.state);
  } catch (e) { log("ERROR: " + e.message); }
});

$("closeBtn").addEventListener("click", async () => {
  try {
    const data = await api("/api/close", { method: "POST", body: "{}" });
    lastPayload = { ...(lastPayload || {}), state: data.state };
    updateState(data.state);
    drawChart(lastPayload?.candles || [], data.state);
    log("ปิดไม้แล้ว", data.state);
  } catch (e) { log("ERROR: " + e.message); }
});

window.addEventListener("resize", () => {
  if (lastPayload) drawChart(lastPayload.candles, lastPayload.state);
});

(async function init() {
  try {
    await loadPresets();
    await loadConfig();
    await loadState();
    await loadLive();
    await loadNews();
    restartLiveTimer();
  } catch (e) {
    log("ERROR: " + e.message);
  }
})();
