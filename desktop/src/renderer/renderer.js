const state = {
  view: "dashboard",
  settings: {},
  history: [],
  tdataPath: "",
  running: false,
  botRunning: false,
  query: "",
  pythonOk: null,
};

const $ = (id) => document.getElementById(id);

const HEAT_ROWS = [
  { label: "9 am", hours: [8, 9] },
  { label: "11 am", hours: [10, 11] },
  { label: "12 pm", hours: [12] },
  { label: "1 pm", hours: [13] },
  { label: "2 pm", hours: [14, 15] },
  { label: "3 pm", hours: [0, 1, 2, 3, 4, 5, 6, 7, 16, 17, 18, 19, 20, 21, 22, 23] },
];
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const PALETTE = ["#3a2422", "#6d2e24", "#c2412c", "#ff4d2a", "#ff7a45"];

function money(value) {
  return new Intl.NumberFormat("en-US").format(Number(value) || 0);
}

function filteredHistory() {
  const q = state.query.trim().toLowerCase();
  if (!q) return state.history;
  return state.history.filter((item) =>
    `${item.name} ${item.link} ${item.tdataPath}`.toLowerCase().includes(q),
  );
}

function okRuns() {
  return filteredHistory().filter((item) => item.ok && item.result);
}

function sum(list, pick) {
  return list.reduce((total, item) => total + Number(pick(item) || 0), 0);
}

function trend(current, previous) {
  if (!previous) return { cls: "flat", text: "0%" };
  const delta = ((current - previous) / Math.abs(previous)) * 100;
  if (!Number.isFinite(delta) || Math.abs(delta) < 0.05) return { cls: "flat", text: "0%" };
  const cls = delta > 0 ? "up" : "down";
  const arrow = delta > 0 ? "↗" : "↘";
  return { cls, text: `${arrow} ${Math.abs(delta).toFixed(1)}%` };
}

function rangeLabel() {
  const items = filteredHistory();
  if (!items.length) return "Запусков пока нет";
  const dates = items.map((item) => new Date(item.at)).sort((a, b) => a - b);
  const fmt = (date) =>
    date.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
  return `${fmt(dates[0])} — ${fmt(dates[dates.length - 1])}`;
}

function metricCard(label, value, trendInfo, sub) {
  return `<article class="metric">
    <div class="label-row"><span class="label">${label}</span><span class="trend ${trendInfo.cls}">${trendInfo.text}</span></div>
    <div class="value">${value}</div>
    <div class="sub">${sub}</div>
  </article>`;
}

function renderMetrics(target) {
  const runs = okRuns();
  const last = runs[0]?.result;
  const prev = runs[1]?.result;
  const sent = sum(runs, (item) => item.result.stars_sent);
  const converted = sum(runs, (item) => item.result.converted);
  const accounts = new Set(runs.map((item) => item.name)).size;
  const success = filteredHistory().length
    ? (runs.length / filteredHistory().length) * 100
    : 0;
  const prevSuccess = state.history.length > 1 ? 50 : 0;
  const html = [
    metricCard("Отправлено звёзд", money(sent), trend(last?.stars_sent || 0, prev?.stars_sent || 0), rangeLabel()),
    metricCard("Подарки в звёзды", money(converted), trend(last?.converted || 0, prev?.converted || 0), rangeLabel()),
    metricCard("Аккаунты", money(accounts), trend(accounts, Math.max(accounts - 1, 0)), rangeLabel()),
    metricCard("Успешные запуски", `${success.toFixed(1)} %`, trend(success, prevSuccess || success), rangeLabel()),
  ].join("");
  $(target).innerHTML = html;
}

function heatColor(value, max) {
  if (!value || !max) return "#2a2a2a";
  const index = Math.min(PALETTE.length - 1, Math.ceil((value / max) * (PALETTE.length - 1)));
  return PALETTE[index];
}

function renderHeatmap() {
  const grid = HEAT_ROWS.map(() => DAYS.map(() => 0));
  for (const item of filteredHistory()) {
    const date = new Date(item.at);
    const day = (date.getDay() + 6) % 7;
    const row = HEAT_ROWS.findIndex((band) => band.hours.includes(date.getHours()));
    if (row >= 0) grid[row][day] += 1;
  }
  const max = Math.max(1, ...grid.flat());
  const rows = HEAT_ROWS.map((band) => `<div class="heat-label">${band.label}</div>`).join("");
  const cells = grid
    .flatMap((row, rowIndex) =>
      row.map((value, col) => {
        const hatched = value > 0 && (rowIndex + col) % 3 === 0 ? " hatched" : "";
        return `<div class="cell${hatched}" style="background-color:${heatColor(value, max)}" title="${DAYS[col]} ${HEAT_ROWS[rowIndex].label}: ${value}"></div>`;
      }),
    )
    .join("");
  $("heatmap").innerHTML = `
    <div class="heat-rows">${rows}</div>
    <div class="heat-grid">${cells}</div>
    <div class="col-labels"><div></div><div>${DAYS.map((day) => `<span>${day}</span>`).join("")}</div></div>`;
  $("heat-legend").innerHTML = [
    ["#6d2e24", "1"],
    ["#c2412c", "2"],
    ["#ff4d2a", "3+"],
  ]
    .map(([color, label]) => `<span><i class="dot" style="background:${color}"></i>${label}</span>`)
    .join("");
}

function niceMax(value) {
  if (value <= 0) return 100;
  const pow = 10 ** Math.floor(Math.log10(value));
  const fraction = value / pow;
  const nice = fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 5 ? 5 : 10;
  return nice * pow;
}

function chartModel(items) {
  const points = items.slice(0, 8).reverse();
  const raw = Math.max(0, ...points.flatMap((item) => [item.result?.stars_sent || 0, item.result?.stars_after || 0]));
  return { points, max: niceMax(raw) };
}

function smooth(points) {
  if (!points.length) return "";
  if (points.length === 1) return `M ${points[0].x} ${points[0].y}`;
  let path = `M ${points[0].x} ${points[0].y}`;
  for (let i = 0; i < points.length - 1; i += 1) {
    const p0 = points[i === 0 ? i : i - 1];
    const p1 = points[i];
    const p2 = points[i + 1];
    const p3 = points[i + 2] || p2;
    const c1x = p1.x + (p2.x - p0.x) / 6;
    const c1y = p1.y + (p2.y - p0.y) / 6;
    const c2x = p2.x - (p3.x - p1.x) / 6;
    const c2y = p2.y - (p3.y - p1.y) / 6;
    path += ` C ${c1x} ${c1y}, ${c2x} ${c2y}, ${p2.x} ${p2.y}`;
  }
  return path;
}

function renderChart(target, tall) {
  const items = okRuns();
  const { points, max } = chartModel(items);
  const width = 640;
  const height = tall ? 260 : 230;
  const pad = { l: 42, r: 12, t: 16, b: 28 };
  const innerW = width - pad.l - pad.r;
  const innerH = height - pad.t - pad.b;
  const yOf = (value) => pad.t + innerH - (value / max) * innerH;
  const xOf = (index) =>
    pad.l + (points.length <= 1 ? innerW / 2 : (index / (points.length - 1)) * innerW);
  const sent = points.map((item, index) => ({ x: xOf(index), y: yOf(item.result.stars_sent) }));
  const left = points.map((item, index) => ({ x: xOf(index), y: yOf(item.result.stars_after) }));
  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((part) => {
    const value = max * part;
    const y = yOf(value);
    const label = Number.isInteger(value) ? String(value) : String(Math.round(value));
    return `<text x="0" y="${y + 4}">${label}</text><line x1="${pad.l}" y1="${y}" x2="${width - pad.r}" y2="${y}" stroke="rgba(255,255,255,.04)" />`;
  });
  const labels = points
    .map((item, index) => {
      const label = new Date(item.at).toLocaleDateString("en-GB", { day: "2-digit", month: "short" });
      return `<text x="${xOf(index)}" y="${height - 8}" text-anchor="middle">${label}</text>`;
    })
    .join("");
  const last = sent[sent.length - 1];
  const tip = last
    ? `<line x1="${last.x}" y1="${pad.t}" x2="${last.x}" y2="${pad.t + innerH}" stroke="rgba(255,255,255,.25)" stroke-dasharray="3 3" />
       <circle cx="${last.x}" cy="${last.y}" r="4" fill="#ff4d2a" />
       <circle cx="${left[left.length - 1].x}" cy="${left[left.length - 1].y}" r="4" fill="#8d8d93" />`
    : "";
  $(target).innerHTML = `<svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none">
    ${yTicks.join("")}
    <path d="${smooth(left)}" fill="none" stroke="#8d8d93" stroke-width="2.5" />
    <path d="${smooth(sent)}" fill="none" stroke="#ff5a36" stroke-width="2.5" />
    ${tip}
    ${labels}
  </svg>`;
}

function growthCell(item, index, list) {
  const prev = list[index + 1];
  if (!item.result || !prev?.result) return `<td class="grow flat">—</td>`;
  const info = trend(item.result.stars_sent, prev.result.stars_sent);
  return `<td class="grow ${info.cls}">${info.text}</td>`;
}

function tableHtml(items, limit) {
  const rows = (limit ? items.slice(0, limit) : items);
  if (!rows.length) {
    return `<table><tr><td>Запусков пока нет. Откройте «Запуск» и выберите tdata.</td></tr></table>`;
  }
  const body = rows
    .map((item, index) => {
      const result = item.result || {};
      return `<tr>
        <td class="name">${item.name || "tdata"}</td>
        <td>${item.ok ? money(result.stars_sent) : "—"}</td>
        <td>${item.ok ? money(result.converted) : "—"}</td>
        ${growthCell(item, index, rows)}
        <td>${item.ok ? money(result.listed) : "—"}</td>
        <td>${item.ok ? money(result.stars_after) : item.error || "ошибка"}</td>
      </tr>`;
    })
    .join("");
  return `<table>
    <thead><tr><th>АККАУНТ</th><th>ЗВЁЗДЫ</th><th>ПОДАРКИ</th><th>РОСТ</th><th>NFT</th><th>ОСТАТОК</th></tr></thead>
    <tbody>${body}</tbody>
  </table>`;
}

function renderAccounts() {
  const items = okRuns().slice(0, 6);
  const colors = ["#1f3b73", "#7a1f2b", "#0e6b4a", "#8a5a12", "#5a2d82", "#114e7a"];
  const cards = (items.length ? items : Array.from({ length: 6 }, () => null))
    .map((item, index) => {
      if (!item) {
        return `<article class="account"><div class="flag" style="background:#2a2a2a"></div><b>—</b><span>нет данных</span></article>`;
      }
      const code = (item.name || "TD").replace(/[^a-z0-9]/gi, "").slice(0, 2).toUpperCase() || "TD";
      return `<article class="account">
        <div class="flag" style="background:${colors[index % colors.length]}">${code}</div>
        <b>${item.name}</b>
        <span>${money(item.result.stars_sent)} ⭐ · ${item.result.converted} подарков</span>
      </article>`;
    })
    .join("");
  $("account-grid").innerHTML = cards;
  $("accounts-table").innerHTML = tableHtml(filteredHistory());
}

function renderAll() {
  renderMetrics("metrics");
  renderMetrics("gift-metrics");
  renderHeatmap();
  renderChart("chart", false);
  renderChart("chart-full", true);
  renderAccounts();
  $("dash-table").innerHTML = tableHtml(filteredHistory(), 4);
  $("history-table").innerHTML = tableHtml(filteredHistory());
  const failed = state.history.some((item) => !item.ok);
  $("bell-dot").hidden = !failed;
}

function showView(name) {
  state.view = name;
  document.querySelectorAll(".view").forEach((view) => {
    view.hidden = view.id !== `view-${name}`;
  });
  document.querySelectorAll(".nav-btn").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === name);
  });
}

function parseLink(url) {
  const match = String(url || "")
    .trim()
    .match(/^https?:\/\/(?:t(?:elegram)?\.me|telegram\.dog)\/(?:c\/(\d+)\/(\d+)|([A-Za-z0-9_]{4,})\/(\d+))\/?(?:\?.*)?$/i);
  if (!match) return null;
  if (match[1]) return { peer: `-100${match[1]}`, msgId: match[2] };
  return { peer: `@${match[3]}`, msgId: match[4] };
}

function paintLink(inputId, previewId) {
  const parsed = parseLink($(inputId).value);
  $(previewId).textContent = parsed
    ? `Пост ${parsed.peer}, сообщение ${parsed.msgId}`
    : "Нужна ссылка вида https://t.me/channel/32";
}

function fillForms() {
  const settings = state.settings;
  $("run-link").value = settings.channelPostUrl || "";
  $("channel-link").value = settings.channelPostUrl || "";
  $("run-mode").value = settings.sellMode || "both";
  $("run-price").value = settings.resellPrice ?? 0;
  $("run-keep").value = settings.keepStars ?? 0;
  $("set-api-id").value = settings.apiId || "";
  $("set-api-hash").value = settings.apiHash || "";
  $("set-token").value = settings.botToken || "";
  $("set-batch").value = settings.maxBatch ?? 2500;
  paintLink("run-link", "link-preview");
  paintLink("channel-link", "channel-preview");
}

function collectSettings() {
  return {
    channelPostUrl: $("channel-link").value.trim() || $("run-link").value.trim(),
    sellMode: $("run-mode").value,
    resellPrice: Number($("run-price").value || 0),
    keepStars: Number($("run-keep").value || 0),
    maxBatch: Number($("set-batch").value || 2500),
    apiId: $("set-api-id").value.trim(),
    apiHash: $("set-api-hash").value.trim(),
    botToken: $("set-token").value.trim(),
  };
}

function appendLog(id, line) {
  const node = $(id);
  node.textContent += `${line}\n`;
  node.scrollTop = node.scrollHeight;
}

function setPath(filePath) {
  state.tdataPath = filePath || "";
  $("tdata-path").textContent = state.tdataPath || "Файл ещё не выбран";
}

async function boot() {
  const today = new Date();
  $("today").textContent = today.toLocaleDateString("en-GB", {
    weekday: "short",
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
  const snapshot = await window.desktop.getState();
  state.settings = snapshot.settings;
  state.history = snapshot.history || [];
  state.botRunning = snapshot.botRunning;
  fillForms();
  renderAll();
  const initialView = new URLSearchParams(window.location.search).get("view");
  if (initialView) showView(initialView);
  $("bot-state").textContent = state.botRunning ? "Запущен" : "Остановлен";
  $("bot-toggle").textContent = state.botRunning ? "Остановить бота" : "Запустить бота";
  const python = await window.desktop.checkPython();
  state.pythonOk = python.ok;
  $("python-status").textContent = python.ok
    ? `Python готов: ${snapshot.python}`
    : `Python-зависимости не найдены. Выполните pip install -r requirements.txt. ${python.error || ""}`;
}

document.querySelectorAll(".nav-btn").forEach((button) => {
  button.addEventListener("click", () => showView(button.dataset.view));
});
document.querySelectorAll("[data-jump]").forEach((button) => {
  button.addEventListener("click", () => showView(button.dataset.jump));
});

$("search").addEventListener("input", (event) => {
  state.query = event.target.value;
  renderAll();
});
$("run-link").addEventListener("input", () => {
  $("channel-link").value = $("run-link").value;
  paintLink("run-link", "link-preview");
  paintLink("channel-link", "channel-preview");
});
$("channel-link").addEventListener("input", () => {
  $("run-link").value = $("channel-link").value;
  paintLink("channel-link", "channel-preview");
  paintLink("run-link", "link-preview");
});

$("pick-folder").addEventListener("click", async () => setPath(await window.desktop.pickFolder()));
$("pick-zip").addEventListener("click", async () => setPath(await window.desktop.pickZip()));

const drop = $("drop");
["dragenter", "dragover"].forEach((name) =>
  drop.addEventListener(name, (event) => {
    event.preventDefault();
    drop.classList.add("drag");
  }),
);
["dragleave", "drop"].forEach((name) =>
  drop.addEventListener(name, (event) => {
    event.preventDefault();
    drop.classList.remove("drag");
  }),
);
drop.addEventListener("drop", (event) => {
  const file = event.dataTransfer.files?.[0];
  if (file) setPath(window.desktop.getPathForFile(file));
});

$("save-channel").addEventListener("click", async () => {
  state.settings = await window.desktop.saveSettings({
    ...collectSettings(),
    channelPostUrl: $("channel-link").value.trim(),
  });
  fillForms();
});

$("save-settings").addEventListener("click", async () => {
  state.settings = await window.desktop.saveSettings(collectSettings());
  fillForms();
  appendLog("bot-log", "Настройки сохранены");
});

$("run-btn").addEventListener("click", async () => {
  if (state.running) return;
  if (!parseLink($("run-link").value)) {
    appendLog("log", "Ссылка на пост не распознана");
    return;
  }
  if (!state.tdataPath) {
    appendLog("log", "Сначала выберите tdata");
    return;
  }
  state.running = true;
  $("run-btn").disabled = true;
  $("run-state").textContent = "Обработка…";
  state.settings = await window.desktop.saveSettings({
    ...collectSettings(),
    channelPostUrl: $("run-link").value.trim(),
  });
  try {
    const done = await window.desktop.run({
      tdataPath: state.tdataPath,
      link: $("run-link").value.trim(),
      passcode: $("run-pass").value,
      settings: state.settings,
    });
    state.history = done.history;
    renderAll();
    $("run-state").textContent = done.entry.ok ? "Готово" : "Ошибка";
  } catch (error) {
    appendLog("log", error.message || String(error));
    $("run-state").textContent = "Ошибка";
  } finally {
    state.running = false;
    $("run-btn").disabled = false;
    $("run-pass").value = "";
  }
});

$("bot-toggle").addEventListener("click", async () => {
  try {
    if (state.botRunning) {
      await window.desktop.stopBot();
      state.botRunning = false;
    } else {
      state.settings = await window.desktop.saveSettings(collectSettings());
      await window.desktop.startBot();
      state.botRunning = true;
    }
  } catch (error) {
    appendLog("bot-log", error.message || String(error));
  }
  $("bot-state").textContent = state.botRunning ? "Запущен" : "Остановлен";
  $("bot-toggle").textContent = state.botRunning ? "Остановить бота" : "Запустить бота";
});

$("clear-history").addEventListener("click", async () => {
  state.history = await window.desktop.clearHistory();
  renderAll();
});

$("bell").addEventListener("click", () => showView("analysis"));
$("win-min").addEventListener("click", () => window.desktop.minimize());
$("win-max").addEventListener("click", () => window.desktop.maximize());
$("win-close").addEventListener("click", () => window.desktop.close());

window.desktop.onLog((line) => appendLog("log", line));
window.desktop.onBotLog((line) => appendLog("bot-log", line));
window.desktop.onBotStatus((payload) => {
  state.botRunning = Boolean(payload.running);
  $("bot-state").textContent = state.botRunning ? "Запущен" : "Остановлен";
  $("bot-toggle").textContent = state.botRunning ? "Остановить бота" : "Запустить бота";
});

boot().catch((error) => {
  $("python-status").textContent = error.message || String(error);
});
