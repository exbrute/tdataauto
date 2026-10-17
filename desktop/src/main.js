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
};

let mainWindow = null;
let runChild = null;
let botChild = null;

function settingsFile() {
  return path.join(app.getPath("userData"), "settings.json");
}

function historyFile() {
  return path.join(app.getPath("userData"), "history.json");
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
    backgroundColor: "#d39270",
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
  python: resolvePython(),
  repoRoot: app.isPackaged ? process.resourcesPath : projectRoot(),
  botRunning: Boolean(botChild && !botChild.killed),
  runBusy: Boolean(runChild && !runChild.killed),
}));

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

ipcMain.handle("pipeline:run", async (_event, payload) => {
  if (runChild) throw new Error("Обработка уже выполняется");
  const settings = { ...loadSettings(), ...(payload.settings || {}) };
  const link = String(payload.link || settings.channelPostUrl || "").trim();
  if (!link) throw new Error("Укажите ссылку на пост канала");
  let tdataPath = String(payload.tdataPath || "").trim();
  if (!tdataPath) throw new Error("Выберите папку tdata или ZIP");
  if (!fs.existsSync(tdataPath)) throw new Error("Путь к tdata не найден");

  const python = resolvePython();
  if (tdataPath.toLowerCase().endsWith(".zip")) {
    tdataPath = await extractZip(python, tdataPath);
  }

  const args = ["-m", "tdataauto", "run", "--tdata", tdataPath, "--link", link, "--json", "-v"];
  const child = spawn(python, args, {
    env: pythonSpawnEnv(settings, payload.passcode),
    windowsHide: true,
  });
  runChild = child;

  let stdout = "";
  const sendLog = (line) => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send("pipeline:log", line);
    }
  };

  child.stdout.on("data", (chunk) => {
    stdout += chunk.toString();
    chunk.toString().split(/\r?\n/).filter(Boolean).forEach(sendLog);
  });
  child.stderr.on("data", (chunk) => {
    chunk.toString().split(/\r?\n/).filter(Boolean).forEach(sendLog);
  });
  child.on("error", (err) => sendLog(err.message));

  return new Promise((resolve) => {
    child.on("close", (code) => {
      runChild = null;
      const marker = stdout
        .split("\n")
        .reverse()
        .find((line) => line.startsWith("TDATA_RESULT "));
      let result = null;
      if (marker) {
        try {
          result = JSON.parse(marker.slice("TDATA_RESULT ".length));
        } catch {
          result = null;
        }
      }
      const entry = {
        id: Date.now(),
        at: new Date().toISOString(),
        name: path.basename(payload.tdataPath),
        tdataPath: payload.tdataPath,
        link,
        ok: code === 0 && Boolean(result),
        code,
        result,
        error: code === 0 ? "" : "Обработка завершилась с ошибкой. Смотрите журнал.",
      };
      const history = readJson(historyFile(), []);
      history.unshift(entry);
      const trimmed = history.slice(0, 200);
      writeJson(historyFile(), trimmed);
      const done = { entry, history: trimmed };
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send("pipeline:done", done);
      }
      resolve(done);
    });
  });
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
