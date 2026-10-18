const { contextBridge, ipcRenderer, webUtils } = require("electron");

function subscribe(channel, callback) {
  const listener = (_event, payload) => callback(payload);
  ipcRenderer.on(channel, listener);
  return () => ipcRenderer.removeListener(channel, listener);
}

contextBridge.exposeInMainWorld("desktop", {
  getState: () => ipcRenderer.invoke("state:get"),
  saveSettings: (settings) => ipcRenderer.invoke("settings:save", settings),
  pickFolder: () => ipcRenderer.invoke("dialog:folder"),
  pickZip: () => ipcRenderer.invoke("dialog:zip"),
  checkPython: () => ipcRenderer.invoke("python:check"),
  run: (payload) => ipcRenderer.invoke("pipeline:run", payload),
  startBot: () => ipcRenderer.invoke("bot:start"),
  stopBot: () => ipcRenderer.invoke("bot:stop"),
  clearHistory: () => ipcRenderer.invoke("history:clear"),
  saveLibrary: (library) => ipcRenderer.invoke("library:save", library),
  listSessions: () => ipcRenderer.invoke("sessions:list"),
  deleteSession: (name) => ipcRenderer.invoke("sessions:delete", name),
  getPathForFile: (file) => webUtils.getPathForFile(file),
  minimize: () => ipcRenderer.invoke("window:minimize"),
  maximize: () => ipcRenderer.invoke("window:maximize"),
  close: () => ipcRenderer.invoke("window:close"),
  onLog: (callback) => subscribe("pipeline:log", callback),
  onDone: (callback) => subscribe("pipeline:done", callback),
  onBotLog: (callback) => subscribe("bot:log", callback),
  onBotStatus: (callback) => subscribe("bot:status", callback),
});
