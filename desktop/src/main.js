const { app, BrowserWindow, ipcMain, dialog } = require("electron");
const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");

app.commandLine.appendSwitch("no-sandbox");
app.commandLine.appendSwitch("disable-gpu");

function projectRoot() {
  return path.resolve(__dirname, "..", "..");
}

function dataDir() {
  const base = app.isPackaged
    ? path.join(app.getPath("userData"), "data")
    : path.join(projectRoot(), "data");
  fs.mkdirSync(base, { recursive: true });
  return base;
}
const defaultSettings = {
  channelPostUrl: "",
  sellMode: "both",
  resellPrice: 0,
  keepStars: 0,
  maxBatch: 2500,
  apiId: "",
  apiHash: "",
  botToken: "",
  defaultProxyId: "",
};

let mainWindow = null;
let runChild = null;
let botChild = null;
let pythonJobChain = Promise.resolve();

function settingsFile() {
  return path.join(app.getPath("userData"), "settings.json");
}

function historyFile() {
  return path.join(app.getPath("userData"), "history.json");
}

function libraryFile() {
  return path.join(app.getPath("userData"), "library.json");
}

function loadLibrary() {
  const data = readJson(libraryFile(), {});
  return {
    pool: Array.isArray(data.pool) ? data.pool : [],
    folders: Array.isArray(data.folders) ? data.folders : [],
    proxies: Array.isArray(data.proxies) ? data.proxies : [],
  };
}

function sendPoolUpdated(library) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send("pool:updated", library);
  }
}

function enqueuePythonJob(task) {
  const job = pythonJobChain.then(task);
  pythonJobChain = job.catch(() => {});
  return job;
}

function listSessionFiles() {
  const dir = path.join(dataDir(), "sessions");
  if (!fs.existsSync(dir)) return [];
  return fs
    .readdirSync(dir)
    .filter((name) => name.endsWith(".session"))
    .map((name) => {
      const stat = fs.statSync(path.join(dir, name));
      return { name, size: stat.size, mtime: stat.mtimeMs };
    })
    .sort((a, b) => b.mtime - a.mtime);
}

function readJson(file, fallback) {
  try {
    return JSON.parse(fs.readFileSync(file, "utf8"));
  } catch {
    return fallback;
  }
}

function writeJson(file, data) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(data, null, 2));
}

function resolvePython() {
  if (app.isPackaged) {
    const bundled = path.join(process.resourcesPath, "python", "python.exe");
    if (fs.existsSync(bundled)) return bundled;
  }
  const venv = path.join(projectRoot(), ".venv", "bin", "python");
  if (fs.existsSync(venv)) return venv;
  if (process.env.TDATA_PYTHON) return process.env.TDATA_PYTHON;
  return process.platform === "win32" ? "python" : "python3";
}

function pythonSpawnEnv(settings, passcode) {
  const env = settingsToEnv(settings, passcode);
  env.PYTHONUTF8 = "1";
  env.PYTHONIOENCODING = "utf-8";
  env.QT_QPA_PLATFORM = "offscreen";
  if (!app.isPackaged) env.PYTHONPATH = projectRoot();
  return env;
}

function loadSettings() {
  return { ...defaultSettings, ...readJson(settingsFile(), {}) };
}

function settingsToEnv(settings, passcode) {
  const env = { ...process.env, PYTHONUNBUFFERED: "1" };
  if (settings.apiId) env.API_ID = String(settings.apiId).trim();
  if (settings.apiHash) env.API_HASH = String(settings.apiHash).trim();
  if (settings.botToken) env.BOT_TOKEN = String(settings.botToken).trim();
  if (settings.channelPostUrl) env.CHANNEL_POST_URL = String(settings.channelPostUrl).trim();
  env.SELL_MODE = settings.sellMode || "both";
  env.RESELL_PRICE = String(Number(settings.resellPrice) || 0);
  env.KEEP_STARS = String(Number(settings.keepStars) || 0);
  env.MAX_PAID_REACTION_BATCH = String(Number(settings.maxBatch) || 2500);
  env.DATA_DIR = dataDir();
  if (passcode) env.TDATA_PASSCODE = String(passcode);
  else delete env.TDATA_PASSCODE;
  return env;
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 940,
    minWidth: 1180,
    minHeight: 760,
    frame: false,
    backgroundColor: "#141414",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });
  const query = {};
  if (process.env.STARFLOW_VIEW) query.view = process.env.STARFLOW_VIEW;
  mainWindow.loadFile(path.join(__dirname, "renderer", "index.html"), { query });
  if (process.env.STARFLOW_SHOT) {
    mainWindow.webContents.once("did-finish-load", async () => {
      await new Promise((resolve) => setTimeout(resolve, 1500));
      const image = await mainWindow.webContents.capturePage();
      fs.writeFileSync(process.env.STARFLOW_SHOT, image.toPNG());
      app.quit();
    });
  }
}

app.whenReady().then(createWindow);

app.on("window-all-closed", () => {
  if (runChild) runChild.kill();
  if (botChild) botChild.kill();
  app.quit();
});

ipcMain.handle("window:minimize", () => mainWindow && mainWindow.minimize());
ipcMain.handle("window:maximize", () => {
  if (!mainWindow) return;
  if (mainWindow.isMaximized()) mainWindow.unmaximize();
  else mainWindow.maximize();
});
ipcMain.handle("window:close", () => mainWindow && mainWindow.close());

ipcMain.handle("state:get", () => ({
  settings: loadSettings(),
  history: readJson(historyFile(), []),
  library: loadLibrary(),
  sessions: listSessionFiles(),
  python: resolvePython(),
  repoRoot: app.isPackaged ? process.resourcesPath : projectRoot(),
  botRunning: Boolean(botChild && !botChild.killed),
  runBusy: Boolean(runChild && !runChild.killed),
}));

ipcMain.handle("library:save", (_event, library) => {
  const next = {
    pool: Array.isArray(library.pool) ? library.pool : [],
    folders: Array.isArray(library.folders) ? library.folders : [],
    proxies: Array.isArray(library.proxies) ? library.proxies : [],
  };
  writeJson(libraryFile(), next);
  return next;
});

ipcMain.handle("sessions:list", () => listSessionFiles());

ipcMain.handle("sessions:delete", (_event, name) => {
  const safe = path.basename(String(name || ""));
  if (!safe.endsWith(".session")) throw new Error("Некорректное имя сессии");
  const dir = path.join(dataDir(), "sessions");
  for (const suffix of ["", "-journal"]) {
    const file = path.join(dir, `${safe}${suffix}`);
    if (fs.existsSync(file)) fs.unlinkSync(file);
  }
  return listSessionFiles();
});

ipcMain.handle("settings:save", (_event, settings) => {
  const next = { ...defaultSettings, ...settings };
  delete next.passcode;
  writeJson(settingsFile(), next);
  return next;
});

ipcMain.handle("history:clear", () => {
  writeJson(historyFile(), []);
  return [];
});

ipcMain.handle("dialog:folder", async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ["openDirectory"],
  });
  return result.canceled ? null : result.filePaths[0];
});

ipcMain.handle("dialog:zip", async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ["openFile"],
    filters: [{ name: "ZIP", extensions: ["zip"] }],
  });
  return result.canceled ? null : result.filePaths[0];
});

ipcMain.handle("python:check", () => {
  return new Promise((resolve) => {
    const child = spawn(resolvePython(), ["-c", "import telethon, opentele, aiogram"], {
      env: pythonSpawnEnv(loadSettings()),
    });
    let error = "";
    child.stderr.on("data", (chunk) => {
      error += chunk.toString();
    });
    child.on("close", (code) => resolve({ ok: code === 0, error: error.trim() }));
    child.on("error", (err) => resolve({ ok: false, error: err.message }));
  });
});

function extractZip(python, zipPath) {
  const dest = path.join(dataDir(), "tmp", `desktop-${Date.now()}`);
  fs.mkdirSync(dest, { recursive: true });
  return new Promise((resolve, reject) => {
    const child = spawn(
      python,
      [
        "-c",
        "import sys, zipfile\nfrom pathlib import Path\np=Path(sys.argv[2]); p.mkdir(parents=True, exist_ok=True)\nzipfile.ZipFile(sys.argv[1]).extractall(p)\n",
        zipPath,
        dest,
      ],
      { env: pythonSpawnEnv(loadSettings()) },
    );
    let error = "";
    child.stderr.on("data", (chunk) => {
      error += chunk.toString();
    });
    child.on("error", reject);
    child.on("close", (code) => {
      if (code === 0) resolve(dest);
      else reject(new Error(error.trim() || "Не удалось распаковать ZIP"));
    });
  });
}

async function resolveTdataInput(rawPath, python) {
  let tdataPath = String(rawPath || "").trim();
  if (!tdataPath) throw new Error("Путь к tdata не указан");
  if (!fs.existsSync(tdataPath)) throw new Error("Путь к tdata не найден");
  if (tdataPath.toLowerCase().endsWith(".zip")) {
    tdataPath = await extractZip(python, tdataPath);
  }
  return tdataPath;
}

function pipelineSendLog(line) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send("pipeline:log", line);
  }
}

function parseJsonMarker(stdout, prefix) {
  const marker = stdout
    .split("\n")
    .reverse()
    .find((line) => line.startsWith(`${prefix} `));
  if (!marker) return null;
  try {
    return JSON.parse(marker.slice(prefix.length + 1));
  } catch {
    return null;
  }
}

function runPythonModule(args, settings, passcode, proxyUrl) {
  if (runChild) throw new Error("Обработка уже выполняется");
  const python = resolvePython();
  const env = pythonSpawnEnv(settings, passcode);
  if (proxyUrl) env.TDATA_PROXY = String(proxyUrl);
  else delete env.TDATA_PROXY;
  const child = spawn(python, args, { env, windowsHide: true });
  runChild = child;
  let stdout = "";
  let stderr = "";
  child.stdout.on("data", (chunk) => {
    stdout += chunk.toString();
    chunk.toString().split(/\r?\n/).filter(Boolean).forEach(pipelineSendLog);
  });
  child.stderr.on("data", (chunk) => {
    stderr += chunk.toString();
    chunk.toString().split(/\r?\n/).filter(Boolean).forEach(pipelineSendLog);
  });
  child.on("error", (err) => pipelineSendLog(err.message));
  return new Promise((resolve, reject) => {
    child.on("close", (code) => {
      runChild = null;
      resolve({ code, stdout, stderr });
    });
    child.on("error", (err) => {
      runChild = null;
      reject(err);
    });
  });
}

function pushHistory(entry) {
  const history = readJson(historyFile(), []);
  history.unshift(entry);
  const trimmed = history.slice(0, 200);
  writeJson(historyFile(), trimmed);
  const done = { entry, history: trimmed };
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send("pipeline:done", done);
  }
  return done;
}

async function runBatchJob(payload) {
  const settings = { ...loadSettings(), ...(payload.settings || {}) };
  const link = String(payload.link || settings.channelPostUrl || "").trim();
  if (!link) throw new Error("Укажите ссылку на пост канала");
  const rawPaths = Array.isArray(payload.tdataPaths) ? payload.tdataPaths : [];
  if (!rawPaths.length) throw new Error("Пул пуст — добавьте tdata на вкладке «Аккаунты»");

  const python = resolvePython();
  const resolved = [];
  for (const raw of rawPaths) {
    resolved.push(await resolveTdataInput(raw, python));
  }

  const args = ["-m", "tdataauto", "run-batch", "--link", link, "--json", "-v"];
  for (const item of resolved) args.push("--tdata", item);

  const { code, stdout } = await runPythonModule(
    args,
    settings,
    payload.passcode,
    payload.proxyUrl,
  );
  const result = parseJsonMarker(stdout, "TDATA_BATCH_RESULT");
  const entry = {
    id: Date.now(),
    at: new Date().toISOString(),
    name: `Пул (${rawPaths.length})`,
    batch: true,
    poolSize: rawPaths.length,
    tdataPaths: rawPaths,
    link,
    ok: Boolean(result) && (result.succeeded > 0 || code === 0),
    code,
    result,
    error: result ? "" : "Пакетная обработка завершилась с ошибкой. Смотрите журнал.",
  };
  return pushHistory(entry);
}

function scanFailureMessage(stdout, stderr, proxyUrl) {
  const text = `${stdout}\n${stderr}`;
  if (/Connection to Telegram failed|TimeoutError|ConnectionError|Не удалось подключиться/i.test(text)) {
    return proxyUrl
      ? "Таймаут через прокси. Проверьте SOCKS5/HTTP: хост, порт, логин."
      : "Нет связи с Telegram. Добавьте прокси на «Прокси» и выберите в «Прокси для пула».";
  }
  if (/passcode|Не удалось загрузить tdata/i.test(text)) {
    return "Не удалось открыть tdata — проверьте passcode.";
  }
  const line = stderr.split("\n").map((row) => row.trim()).find(Boolean);
  return line || "Не удалось получить профиль аккаунта.";
}

async function inspectPoolEntry(payload) {
  const settings = loadSettings();
  const poolId = String(payload.poolId || "");
  const library = loadLibrary();
  const entry = library.pool.find((item) => item.id === poolId);
  if (!entry) throw new Error("Запись пула не найдена");

  entry.scanStatus = "scanning";
  entry.scanError = "";
  writeJson(libraryFile(), library);
  sendPoolUpdated(library);

  const python = resolvePython();
  const tdataPath = await resolveTdataInput(entry.path, python);
  const args = ["-m", "tdataauto", "inspect-account", "--tdata", tdataPath, "--json", "-v"];
  const proxyUrl = payload.proxyUrl || "";
  const { stdout, stderr } = await runPythonModule(
    args,
    settings,
    payload.passcode,
    proxyUrl,
  );
  const profile = parseJsonMarker(stdout, "TDATA_ACCOUNT_PROFILE");
  entry.profile = profile || null;
  entry.scanStatus = profile ? "ready" : "error";
  entry.scanError = profile ? "" : scanFailureMessage(stdout, stderr, proxyUrl);
  entry.scannedAt = profile?.scanned_at || new Date().toISOString();
  writeJson(libraryFile(), library);
  sendPoolUpdated(library);
  return { poolId, profile, library };
}

ipcMain.handle("pipeline:run-batch", (_event, payload) =>
  enqueuePythonJob(() => runBatchJob(payload)),
);

ipcMain.handle("pool:inspect", (_event, payload) =>
  enqueuePythonJob(() => inspectPoolEntry(payload)),
);

ipcMain.handle("pool:inspect-all", async (_event, payload) => {
  const library = loadLibrary();
  for (const item of library.pool) {
    await enqueuePythonJob(() =>
      inspectPoolEntry({
        poolId: item.id,
        passcode: payload.passcode,
        proxyUrl: payload.proxyUrl,
      }),
    );
  }
  return loadLibrary();
});

ipcMain.handle("bot:start", () => {
  if (botChild) return { running: true };
  const settings = loadSettings();
  if (!String(settings.botToken || "").trim()) {
    throw new Error("Укажите токен бота в настройках");
  }
  const child = spawn(resolvePython(), ["-m", "tdataauto", "bot"], {
    env: pythonSpawnEnv(settings),
    windowsHide: true,
  });
  botChild = child;
  const send = (line) => {
    if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send("bot:log", line);
  };
  child.stdout.on("data", (chunk) => chunk.toString().split(/\r?\n/).filter(Boolean).forEach(send));
  child.stderr.on("data", (chunk) => chunk.toString().split(/\r?\n/).filter(Boolean).forEach(send));
  child.on("close", (code) => {
    botChild = null;
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send("bot:status", { running: false, code });
    }
  });
  child.on("error", (err) => send(err.message));
  return { running: true };
});

ipcMain.handle("bot:stop", () => {
  if (botChild) botChild.kill();
  botChild = null;
  return { running: false };
});
