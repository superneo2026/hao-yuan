#!/usr/bin/env node
"use strict";

const { spawn, spawnSync } = require("child_process");
const fs = require("fs");
const http = require("http");
const os = require("os");
const path = require("path");
const readline = require("readline");

const ROOT = path.resolve(__dirname, "..");
let VERSION = "0.0.0";
try {
  VERSION = JSON.parse(fs.readFileSync(path.join(ROOT, "package.json"), "utf8")).version || VERSION;
} catch {
  /* ignore */
}
const IS_WIN = process.platform === "win32";
const NPM = IS_WIN ? "npm.cmd" : "npm";
const VENV = path.join(ROOT, "api", "env1");
const PYTHON = IS_WIN
  ? path.join(VENV, "Scripts", "python.exe")
  : path.join(VENV, "bin", "python");
const WEB = path.join(ROOT, "web");
const API = path.join(ROOT, "api");
const RUNTIME_FILE = path.join(API, "data", "runtime.json");
const DIST_INDEX = path.join(WEB, "dist", "index.html");
const TOKEN_FILE = path.join(API, "data", "cli-token");
const CLI_SECRET_FILE = path.join(API, "data", "cli-secret");
let TOKEN = (process.env.HAOYUAN_TOKEN || "").trim();
if (!TOKEN) {
  try {
    TOKEN = fs.readFileSync(TOKEN_FILE, "utf8").trim();
  } catch {
    TOKEN = "";
  }
}

function saveToken(token) {
  TOKEN = token;
  try {
    fs.mkdirSync(path.dirname(TOKEN_FILE), { recursive: true });
    fs.writeFileSync(TOKEN_FILE, token);
    return true;
  } catch {
    return false;
  }
}

function clearToken() {
  TOKEN = "";
  try {
    fs.unlinkSync(TOKEN_FILE);
  } catch {
    /* ignore */
  }
}

function cliSecret() {
  try {
    return fs.readFileSync(CLI_SECRET_FILE, "utf8").trim();
  } catch {
    return "";
  }
}

const COLOR = process.stdout.isTTY && !process.env.NO_COLOR;
const C = COLOR
  ? {
      reset: "\x1b[0m",
      dim: "\x1b[2m",
      bold: "\x1b[1m",
      cyan: "\x1b[36m",
      green: "\x1b[32m",
      red: "\x1b[31m",
      yellow: "\x1b[33m",
    }
  : { reset: "", dim: "", bold: "", cyan: "", green: "", red: "", yellow: "" };

function log(msg) {
  process.stdout.write(`[HaoYuan] ${msg}\n`);
}

function warn(msg) {
  process.stderr.write(`[HaoYuan] ${msg}\n`);
}

function fail(msg) {
  warn(msg);
  process.exit(1);
}

function shellQuote(s) {
  if (IS_WIN) return `"${String(s)}"`;
  return /^[A-Za-z0-9_@%+=:,./-]+$/.test(String(s)) ? String(s) : `'${String(s).replace(/'/g, "'\\''")}'`;
}

function run(cmd, args, opts = {}) {
  const lenient = opts.lenient === true;
  const useShell = IS_WIN && /\.(cmd|bat)$/i.test(cmd);
  const cwd = opts.cwd || ROOT;
  log(`${cmd} ${args.join(" ")}`);
  const r = useShell
    ? spawnSync([cmd, ...args.map(shellQuote)].join(" "), { stdio: "inherit", cwd, shell: true })
    : spawnSync(cmd, args, { stdio: "inherit", cwd });
  if (r.error) {
    if (lenient) {
      warn(`跳过（${r.error.message}）`);
      return false;
    }
    fail(r.error.message);
  }
  if (r.status !== 0) {
    if (lenient) {
      warn(`步骤失败（退出码 ${r.status}），首次运行 haoyuan 时会自动重试。`);
      return false;
    }
    process.exit(r.status || 1);
  }
  return true;
}

function findPython() {
  const candidates = IS_WIN ? ["python", "py"] : ["python3", "python"];
  for (const py of candidates) {
    const r = spawnSync(py, ["--version"], { stdio: "ignore" });
    if (!r.error && r.status === 0) return py;
  }
  return null;
}

function ensureVenv() {
  if (fs.existsSync(PYTHON)) return true;
  const py = findPython();
  if (!py) {
    warn("未找到 Python 3.10+。请先安装 Python 后再运行 haoyuan。");
    return false;
  }
  log("创建 Python 虚拟环境 api/env1 ...");
  return run(py, ["-m", "venv", VENV]);
}

function pipArgs() {
  const args = ["-m", "pip", "install"];
  const index = (process.env.HAOYUAN_PIP_INDEX_URL || "").trim();
  if (index) args.push("--index-url", index);
  return args;
}

function installBackend() {
  if (!ensureVenv()) return false;
  run(PYTHON, [...pipArgs(), "--upgrade", "pip"], { lenient: true });
  return run(PYTHON, [...pipArgs(), "-r", path.join(API, "requirements.txt")]);
}

function npmArgs() {
  const args = [
    "install",
    "--no-audit",
    "--no-fund",
    "--prefer-offline",
    "--fetch-retries=2",
    "--fetch-retry-mintimeout=2000",
    "--fetch-retry-maxtimeout=10000",
    "--fetch-timeout=30000",
  ];
  const registry = (process.env.HAOYUAN_NPM_REGISTRY || "").trim();
  if (registry) {
    log(`使用自定义 npm 源: ${registry}`);
    args.push("--registry", registry);
  } else {
    log("使用当前 npm 配置的 registry（可用 HAOYUAN_NPM_REGISTRY 覆盖）");
  }
  return args;
}

const FRONTEND_DEPS = ["vite", "vue", "@vitejs/plugin-vue"];
const NODE_MODULES = path.join(WEB, "node_modules");

function frontendDepsReady() {
  return FRONTEND_DEPS.every((name) =>
    fs.existsSync(path.join(NODE_MODULES, ...name.split("/"), "package.json"))
  );
}

function cleanFrontendDeps() {
  log("检测到不完整的前端依赖（上次安装可能被网络中断），自动清理后重装...");
  try {
    fs.rmSync(NODE_MODULES, { recursive: true, force: true });
  } catch (err) {
    warn(`清理 node_modules 失败: ${err.message}`);
  }
}

function backendReady() {
  const r = spawnSync(PYTHON, ["-c", "import fastapi, uvicorn, aiosqlite"], { stdio: "ignore" });
  return !r.error && r.status === 0;
}

function ensureBackend() {
  if (!fs.existsSync(PYTHON) || !backendReady()) {
    log("安装/修复后端依赖 ...");
    setup({ build: !fs.existsSync(DIST_INDEX) });
  }
}

function installFrontend() {
  if (frontendDepsReady()) return true;
  if (fs.existsSync(NODE_MODULES)) cleanFrontendDeps();
  log("安装前端依赖 ...");
  let ok = run(NPM, npmArgs(), { cwd: WEB, lenient: true });
  if (ok && !frontendDepsReady()) {
    cleanFrontendDeps();
    ok = run(NPM, npmArgs(), { cwd: WEB, lenient: true });
  }
  if (frontendDepsReady()) return true;
  if (fs.existsSync(DIST_INDEX)) {
    warn("前端依赖安装失败，改用已包含的预构建前端（web/dist）继续。");
    return true;
  }
  return ok;
}

function buildFrontend() {
  if (!installFrontend()) return false;
  log("构建前端 ...");
  return run(NPM, ["run", "build"], { cwd: WEB });
}

function setup({ build = true } = {}) {
  ensureConfigFile();
  const ok = installBackend();
  if (build && fs.existsSync(DIST_INDEX)) {
    log("已包含预构建前端（web/dist），跳过前端构建。");
    return ok;
  }
  if (build) buildFrontend();
  return ok;
}

function readApiPort() {
  try {
    const data = JSON.parse(fs.readFileSync(RUNTIME_FILE, "utf8"));
    return Number(data.api_port) || 0;
  } catch {
    return 0;
  }
}

async function healthyPort(port) {
  if (!port) return 0;
  try {
    const res = await fetch(`http://127.0.0.1:${port}/api/health`, {
      signal: AbortSignal.timeout(2000),
    });
    return res.ok ? port : 0;
  } catch {
    return 0;
  }
}

function stopLocalServer(port) {
  if (!port) return false;
  try {
    if (IS_WIN) {
      const r = spawnSync("netstat", ["-ano", "-p", "TCP"], { encoding: "utf8" });
      const pids = new Set();
      for (const line of (r.stdout || "").split(/\r?\n/)) {
        if (!/LISTENING/i.test(line)) continue;
        const cols = line.trim().split(/\s+/);
        if (!cols[1] || !cols[1].endsWith(`:${port}`)) continue;
        const pid = cols[cols.length - 1];
        if (/^\d+$/.test(pid) && pid !== "0") pids.add(pid);
      }
      for (const pid of pids) {
        log(`停止正在运行的豪源服务（端口 ${port}，PID ${pid}）...`);
        spawnSync("taskkill", ["/PID", pid, "/F"], { stdio: "ignore" });
      }
      return pids.size > 0;
    }
    const r = spawnSync("lsof", ["-ti", `tcp:${port}`], { encoding: "utf8" });
    const pids = (r.stdout || "").split(/\s+/).filter((pid) => /^\d+$/.test(pid));
    for (const pid of pids) {
      log(`停止正在运行的豪源服务（端口 ${port}，PID ${pid}）...`);
      spawnSync("kill", ["-TERM", pid], { stdio: "ignore" });
    }
    return pids.length > 0;
  } catch {
    return false;
  }
}

async function waitUntilHealthy(timeoutMs = 180000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const port = readApiPort();
    if (await healthyPort(port)) return port;
    await new Promise((r) => setTimeout(r, 500));
  }
  return 0;
}

function openBrowser(url) {
  try {
    if (IS_WIN) {
      spawn("cmd", ["/c", "start", "", url], { detached: true, stdio: "ignore" }).unref();
    } else if (process.platform === "darwin") {
      spawn("open", [url], { detached: true, stdio: "ignore" }).unref();
    } else {
      spawn("xdg-open", [url], { detached: true, stdio: "ignore" }).unref();
    }
    log(`已在浏览器打开 ${url}`);
  } catch {
    log(`请手动打开 ${url}`);
  }
}

function postinstall() {
  ensureConfigFile();
  if (!findPython()) {
    warn("未检测到 Python 3.10+：npm 安装继续，但首次运行 haoyuan 前请先安装 Python。");
    return;
  }
  log("初始化后端依赖（首次安装约需几分钟）...");
  if (fs.existsSync(DIST_INDEX)) {
    log("已包含预构建前端（web/dist），跳过前端构建。");
    installBackend();
  } else {
    setup({ build: true });
  }
}

async function web(options = {}) {
  const running = await healthyPort(readApiPort());
  if (running) {
    const url = `http://127.0.0.1:${running}`;
    log(`服务已在运行: ${url}`);
    if (options.noOpen) log(`（--no-open 模式，请手动打开 ${url}）`);
    else openBrowser(url);
    return;
  }

  ensureBackend();
  if (!fs.existsSync(DIST_INDEX)) buildFrontend();

  log("启动 API（端口 8030，被占用时自动顺延）...");
  const child = spawn(PYTHON, ["main.py"], {
    cwd: API,
    stdio: "inherit",
    env: process.env,
  });
  child.on("error", (err) => fail(err.message));
  child.on("exit", (code, signal) => {
    if (signal) process.kill(process.pid, signal);
    else process.exit(code == null ? 0 : code);
  });
  for (const sig of ["SIGINT", "SIGTERM"]) {
    process.on(sig, () => child.kill(sig));
  }

  log("等待服务就绪 ...");
  const port = await waitUntilHealthy();
  if (port) {
    const url = `http://127.0.0.1:${port}`;
    log(`豪源已启动: ${url}`);
    if (options.noOpen) log(`（--no-open 模式，请手动打开 ${url}）`);
    else openBrowser(url);
  } else {
    warn("服务启动超时（3 分钟），请检查上方日志。");
  }
}

async function ensureServer() {
  ensureConfigFile();
  const running = await healthyPort(readApiPort());
  if (running) return { port: running, child: null };

  ensureBackend();
  if (!fs.existsSync(DIST_INDEX)) buildFrontend();

  log("启动 API（端口 8030，被占用时自动顺延）...");
  let tail = "";
  const child = spawn(PYTHON, ["main.py"], {
    cwd: API,
    stdio: ["ignore", "pipe", "pipe"],
    env: process.env,
  });
  const keep = (chunk) => {
    tail = (tail + chunk.toString()).slice(-4000);
  };
  child.stdout.on("data", keep);
  child.stderr.on("data", keep);
  child.on("error", (err) => {
    warn(`服务启动失败: ${err.message}`);
    process.exit(1);
  });

  const port = await waitUntilHealthy();
  if (!port) {
    child.kill();
    warn("服务启动超时。服务日志:");
    if (tail) process.stderr.write(tail + "\n");
    process.exit(1);
  }
  log(`服务已就绪: http://127.0.0.1:${port}`);
  return { port, child };
}

function apiHeaders() {
  const headers = { "content-type": "application/json" };
  const secret = cliSecret();
  if (secret) headers["x-haoyuan-cli-secret"] = secret;
  if (TOKEN) {
    headers["authorization"] = `Bearer ${TOKEN}`;
    headers["x-haoyuan-token"] = TOKEN;
  }
  return headers;
}

async function apiJson(port, method, apiPath, body) {
  const res = await fetch(`http://127.0.0.1:${port}${apiPath}`, {
    method,
    headers: apiHeaders(),
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(30000),
  });
  let payload = null;
  try {
    payload = await res.json();
  } catch {
    /* ignore */
  }
  if (!payload || payload.code !== 200) {
    throw new Error((payload && payload.message) || `HTTP ${res.status}`);
  }
  return payload.data;
}

function shortJson(value, limit = 120) {
  let text;
  try {
    text = JSON.stringify(value);
  } catch {
    text = String(value);
  }
  if (!text) text = "";
  return text.length > limit ? `${text.slice(0, limit)}…` : text;
}

function ask(rl, promptText, { mute = false } = {}) {
  return new Promise((resolve) => {
    if (!mute) {
      rl.question(promptText, resolve);
      return;
    }
    process.stdout.write(promptText);
    const original = rl._writeToOutput;
    rl._writeToOutput = () => {};
    rl.question("", (answer) => {
      rl._writeToOutput = original;
      process.stdout.write("\n");
      resolve(answer);
    });
  });
}

async function loginAt(port, rl) {
  const statusRes = await fetch(`http://127.0.0.1:${port}/api/auth/status`, {
    signal: AbortSignal.timeout(10000),
  });
  const status = await statusRes.json().catch(() => null);
  const data = (status && status.data) || {};
  if (!data.configured) {
    log("该实例未开启账号保护，无需登录。");
    return "";
  }
  const username = (await ask(rl, `用户名${data.username ? `（${data.username}）` : ""}: `)).trim();
  const password = await ask(rl, "密码: ", { mute: true });
  const res = await fetch(`http://127.0.0.1:${port}/api/auth/login`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ username, password }),
    signal: AbortSignal.timeout(15000),
  });
  const payload = await res.json().catch(() => null);
  if (!payload || payload.code !== 200) {
    throw new Error((payload && payload.message) || `HTTP ${res.status}`);
  }
  saveToken(payload.data.token);
  log(`已登录: ${payload.data.username || username}`);
  return payload.data.token;
}

async function loginCommand() {
  const { port, child } = await ensureServer();
  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
    terminal: process.stdin.isTTY === true,
  });
  try {
    await loginAt(port, rl);
  } catch (err) {
    warn(`登录失败: ${err.message}`);
  } finally {
    try {
      rl.close();
    } catch {
      /* ignore */
    }
    if (child) {
      try {
        child.kill();
      } catch {
        /* ignore */
      }
    }
  }
}

function logoutCommand() {
  clearToken();
  log("已清除本地 CLI 令牌。");
}

const CONFIG_TEMPLATE = JSON.stringify(
  {
    _help:
      "HaoYuan 全局配置。优先级：环境变量 > 本文件 > api/configs/secrets_local.py。" +
      "内置渠道用 DEEPSEEK_* / ZHIPU_* / MIMO_* 字段；任意 OpenAI 兼容渠道写到 providers 对象，" +
      "例如 providers: {\"my-provider\": {\"base_url\": \"https://...\", \"api_key\": \"...\", " +
      "\"models\": [\"model-a\", \"model-b\"], \"default_model\": \"model-a\"}}。" +
      "网页设置页保存时会同步写入本文件。",
    PROVIDER: "",
    MODEL: "",
    DEEPSEEK_API_KEY: "",
    DEEPSEEK_BASE_URL: "https://api.deepseek.com",
    DEEPSEEK_MODEL: "deepseek-flash",
    ZHIPU_API_KEY: "",
    ZHIPU_BASE_URL: "https://open.bigmodel.cn/api/coding/paas/v4",
    ZHIPU_MODEL: "glm-5.3-flash",
    MIMO_API_KEY: "",
    MIMO_BASE_URL: "https://token-plan-cn.xiaomimimo.com/v1",
    MIMO_MODEL: "mimo-v2.6-flash",
    providers: {},
  },
  null,
  2
);

function configFilePath() {
  return process.env.HAOYUAN_CONFIG
    ? path.resolve(process.env.HAOYUAN_CONFIG)
    : path.join(os.homedir(), ".config", "haoyuan", "config.json");
}

function ensureConfigFile() {
  const file = configFilePath();
  try {
    if (!fs.existsSync(file)) {
      fs.mkdirSync(path.dirname(file), { recursive: true });
      fs.writeFileSync(file, `${CONFIG_TEMPLATE}\n`, { mode: 0o600 });
      log(`已生成全局配置文件: ${file}`);
    }
  } catch (err) {
    warn(`无法创建全局配置文件 ${file}: ${err.message}`);
  }
  return file;
}

function configCommand({ open = false } = {}) {
  const existed = fs.existsSync(configFilePath());
  const file = ensureConfigFile();
  log(`全局配置文件: ${file}${existed ? "" : "（已创建）"}${open ? "" : "（可用 --open 打开编辑）"}`);
  if (open && IS_WIN) {
    spawn("cmd", ["/c", "start", "", "notepad.exe", file], { detached: true, stdio: "ignore" }).unref();
  } else if (open && process.platform === "darwin") {
    spawn("open", [file], { detached: true, stdio: "ignore" }).unref();
  } else if (open) {
    spawn("xdg-open", [file], { detached: true, stdio: "ignore" }).unref();
  }
  process.stdout.write(
    [
      "",
      "填写示例（JSON，优先级：环境变量 > 本文件 > api/configs/secrets_local.py）：",
      CONFIG_TEMPLATE.replace(/: "",/g, ': "",'),
      "",
      "保存后无需重启：服务会自动热加载；网页「设置 → 模型配置」也会双向同步本文件。",
      "",
    ].join("\n")
  );
}

async function chat(options = {}) {
  const { port, child: serverChild } = await ensureServer();

  const die = (msg) => {
    if (serverChild) {
      try {
        serverChild.kill();
      } catch {
        /* ignore */
      }
    }
    fail(msg);
  };

  const state = {
    sessionId: "",
    model: "",
    busy: false,
    approval: null,
    picking: null,
    inText: false,
    inReasoning: false,
    streamReq: null,
    lastEventId: 0,
    closing: false,
  };

  let rl = null;

  function prompt() {
    if (state.closing) return;
    rl.setPrompt(`${C.cyan}>${C.reset} `);
    rl.prompt();
  }

  function endLine() {
    if (state.inText || state.inReasoning) {
      process.stdout.write(`${C.reset}\n`);
      state.inText = false;
      state.inReasoning = false;
    }
  }

  function shutdown(code = 0) {
    state.closing = true;
    closeStream();
    try {
      rl.close();
    } catch {
      /* ignore */
    }
    if (serverChild) {
      try {
        serverChild.kill();
      } catch {
        /* ignore */
      }
    }
    process.exit(code);
  }

  function closeStream() {
    if (state.streamReq) {
      try {
        state.streamReq.destroy();
      } catch {
        /* ignore */
      }
      state.streamReq = null;
    }
  }

  function openStream() {
    if (state.streamReq || state.closing) return;
    const qs = `after_id=${state.lastEventId}${TOKEN ? `&token=${encodeURIComponent(TOKEN)}` : ""}`;
    const headers = { Accept: "text/event-stream" };
    const secret = cliSecret();
    if (secret) headers["x-haoyuan-cli-secret"] = secret;
    if (TOKEN) headers["x-haoyuan-token"] = TOKEN;
    const req = http.get(
      {
        host: "127.0.0.1",
        port,
        path: `/api/sessions/${encodeURIComponent(state.sessionId)}/stream?${qs}`,
        headers,
      },
      (res) => {
        if (res.statusCode !== 200) {
          res.resume();
          state.streamReq = null;
          if (state.busy) setTimeout(openStream, 500);
          return;
        }
        let buf = "";
        res.setEncoding("utf8");
        res.on("data", (chunk) => {
          buf += chunk;
          let idx;
          while ((idx = buf.indexOf("\n\n")) >= 0) {
            const block = buf.slice(0, idx);
            buf = buf.slice(idx + 2);
            const data = block
              .split("\n")
              .filter((line) => line.startsWith("data:"))
              .map((line) => line.slice(5).trim())
              .join("");
            if (!data) continue;
            let event;
            try {
              event = JSON.parse(data);
            } catch {
              continue;
            }
            handleEvent(event);
          }
        });
        res.on("end", () => {
          state.streamReq = null;
          if (state.busy && !state.closing) setTimeout(openStream, 600);
        });
        res.on("error", () => {
          state.streamReq = null;
        });
      }
    );
    req.on("error", () => {
      state.streamReq = null;
      if (state.busy && !state.closing) setTimeout(openStream, 800);
    });
    state.streamReq = req;
  }

  function handleEvent(event) {
    if (event && event.id !== undefined) {
      const id = Number(event.id);
      if (Number.isFinite(id) && id > state.lastEventId) state.lastEventId = id;
    }
    const type = event.type || event.event;
    const payload = event.payload || {};

    if (type === "stream.end") {
      state.streamReq = null;
      if (state.busy) {
        state.busy = false;
        endLine();
        prompt();
      }
      return;
    }

    if (type === "delta") {
      if (state.inReasoning) {
        process.stdout.write(`${C.reset}\n`);
        state.inReasoning = false;
      }
      if (!state.inText) {
        process.stdout.write(`${C.bold}[HaoYuan]${C.reset} `);
        state.inText = true;
      }
      if (payload.text) process.stdout.write(payload.text);
      return;
    }

    if (type === "reasoning") {
      if (payload.text) {
        if (!state.inReasoning) {
          process.stdout.write(`${C.dim}[思考] `);
          state.inReasoning = true;
        }
        process.stdout.write(payload.text);
      }
      return;
    }

    if (type === "tool.start") {
      endLine();
      process.stdout.write(`${C.cyan}[工具]${C.reset} ${payload.tool} ${C.dim}${shortJson(payload.args)}${C.reset}\n`);
      return;
    }

    if (type === "tool.end") {
      const mark = payload.ok ? `${C.green}[完成]${C.reset}` : `${C.red}[失败]${C.reset}`;
      const ms = payload.ms != null ? ` ${C.dim}${payload.ms}ms${C.reset}` : "";
      const detail = payload.ok ? payload.summary || "" : payload.error || "";
      process.stdout.write(`${mark} ${payload.tool}${ms}${detail ? ` ${C.dim}${shortJson(detail, 160)}${C.reset}` : ""}\n`);
      return;
    }

    if (type === "approval.required") {
      endLine();
      state.approval = payload;
      process.stdout.write(
        `${C.yellow}[审批]${C.reset} ${payload.tool} 需要确认 ${C.dim}${shortJson(payload.args, 200)}${C.reset}\n`
      );
      if (payload.preview) {
        process.stdout.write(`${C.dim}${shortJson(payload.preview, 400)}${C.reset}\n`);
      }
      rl.setPrompt(`${C.yellow}批准执行? (y/N)${C.reset} `);
      rl.prompt();
      return;
    }

    if (type === "approval.resolved") {
      state.approval = null;
      return;
    }

    if (type === "error") {
      endLine();
      process.stdout.write(`${C.red}[错误] ${payload.message || "未知错误"}${C.reset}\n`);
      return;
    }

    if (type === "done") {
      if (!state.inText && payload.text) {
        process.stdout.write(`${C.bold}[HaoYuan]${C.reset} ${payload.text}\n`);
      }
      endLine();
      if (state.busy) {
        state.busy = false;
        prompt();
      }
      return;
    }

    if (type === "session.status") {
      if (payload.status === "error" && payload.error) {
        endLine();
        process.stdout.write(`${C.red}[错误] ${payload.error}${C.reset}\n`);
      }
    }
  }

  async function resolveApproval(approved) {
    const approval = state.approval;
    state.approval = null;
    rl.setPrompt(`${C.cyan}>${C.reset} `);
    if (!approval) return;
    try {
      await apiJson(port, "POST", `/api/approvals/${encodeURIComponent(approval.approval_id)}/resolve`, {
        approved,
        reason: approved ? "approved from CLI" : "rejected from CLI",
      });
      process.stdout.write(`${approved ? C.green : C.red}[${approved ? "已批准" : "已拒绝"}]${C.reset}\n`);
    } catch (err) {
      warn(`审批提交失败: ${err.message}`);
    }
  }

  async function newSession() {
    const body = { kind: "auto", workspace: process.cwd() };
    const wanted = (options.model || "").trim();
    if (wanted) {
      const slash = wanted.indexOf("/");
      if (slash > 0) {
        body.provider = wanted.slice(0, slash);
        body.model = wanted.slice(slash + 1);
      } else {
        body.model = wanted;
      }
    }
    const data = await apiJson(port, "POST", "/api/sessions", body);
    state.sessionId = data.id;
    state.model = `${data.provider || "mock"}/${data.model || "auto"}`;
    state.lastEventId = 0;
    openStream();
    return data;
  }

  async function sendMessage(text) {
    state.busy = true;
    try {
      await apiJson(port, "POST", `/api/sessions/${encodeURIComponent(state.sessionId)}/messages`, {
        content: text,
        locale: "",
      });
      if (!state.streamReq) openStream();
    } catch (err) {
      state.busy = false;
      warn(`发送失败: ${err.message}`);
      prompt();
    }
  }

  async function cancelRun() {
    try {
      await apiJson(port, "POST", `/api/sessions/${encodeURIComponent(state.sessionId)}/cancel`, {});
      process.stdout.write(`${C.yellow}[已取消当前任务]${C.reset}\n`);
    } catch (err) {
      warn(`取消失败: ${err.message}`);
    }
  }

  function chatHelp() {
    process.stdout.write(
      [
        `${C.bold}终端命令${C.reset}`,
        "  /models [x/y]  查看/选择模型（如 /model deepseek/deepseek-flash）",
        "  /new           新建会话",
        "  /web           在浏览器打开当前会话",
        "  /cancel        取消当前任务",
        "  /exit          退出（输入 exit/quit 或 Ctrl+C 也可退出）",
        "",
      ].join("\n")
    );
  }

  function buildModelOptions(providers) {
    const options = [{ provider: "mock", model: "mock-deterministic", configured: true }];
    for (const p of providers || []) {
      for (const m of p.models || []) {
        options.push({
          provider: p.provider,
          model: m,
          configured: !!p.configured,
          default: m === p.default_model,
        });
      }
    }
    return options;
  }

  function printModelOptions(options) {
    process.stdout.write(`${C.bold}可用模型:${C.reset}\n`);
    options.forEach((opt, i) => {
      const label = `${opt.provider}/${opt.model}`;
      const parts = [`  ${i + 1}) ${label}`];
      if (label === state.model) parts.push(`${C.green}* 当前${C.reset}`);
      if (opt.provider === "mock") parts.push(`${C.dim}(本地调试)${C.reset}`);
      else if (!opt.configured) parts.push(`${C.dim}(Key 未配置，选择后无法调用)${C.reset}`);
      else if (opt.default) parts.push(`${C.dim}(该厂商默认)${C.reset}`);
      process.stdout.write(parts.join(" ") + "\n");
    });
  }

  async function setModel(opt) {
    try {
      await apiJson(port, "PATCH", `/api/sessions/${encodeURIComponent(state.sessionId)}`, {
        provider: opt.provider,
        model: opt.model,
      });
      state.model = `${opt.provider}/${opt.model}`;
      process.stdout.write(`${C.green}[已切换模型] ${state.model}${C.reset}\n`);
    } catch (err) {
      warn(`切换失败: ${err.message}`);
    }
  }

  async function handlePick(text) {
    const pick = state.picking;
    if (!text) {
      state.picking = null;
      process.stdout.write(`${C.dim}[已取消选择]${C.reset}\n`);
      return prompt();
    }
    const idx = Number.parseInt(text, 10);
    if (!Number.isFinite(idx) || idx < 1 || idx > pick.options.length) {
      process.stdout.write(`${C.dim}请输入 1-${pick.options.length} 的序号，或回车取消:${C.reset} `);
      return;
    }
    state.picking = null;
    await setModel(pick.options[idx - 1]);
    return prompt();
  }

  async function modelsCommand(argModel) {
    const data = await apiJson(port, "GET", "/api/models");
    const options = buildModelOptions(data && data.providers);
    if (argModel) {
      const slash = argModel.indexOf("/");
      const opt = options.find((o) =>
        slash > 0 ? `${o.provider}/${o.model}` === argModel : o.model === argModel
      );
      if (!opt) {
        warn(`未知模型: ${argModel}（/models 查看可用列表）`);
        return prompt();
      }
      await setModel(opt);
      return prompt();
    }
    state.picking = { options };
    printModelOptions(options);
    rl.setPrompt(`${C.cyan}选择序号>${C.reset} `);
    rl.prompt();
  }

  async function handleLine(line) {
    const text = line.trim();
    if (!text) {
      prompt();
      return;
    }

    // Windows cmd 等终端里直接输入 exit/quit 也退出对话（无需加 /）
    if (/^(exit|quit)$/i.test(text)) {
      shutdown(0);
      return;
    }

    if (state.approval) {
      if (/^y(es)?$/i.test(text)) await resolveApproval(true);
      else await resolveApproval(false);
      prompt();
      return;
    }

    if (state.picking) {
      await handlePick(text);
      return;
    }

    if (text.startsWith("/")) {
      const cmd = text.split(/\s+/, 1)[0].toLowerCase();
      if (cmd === "/exit" || cmd === "/quit") return shutdown(0);
      if (cmd === "/help") {
        chatHelp();
        return prompt();
      }
      if (cmd === "/models" || cmd === "/model") {
        const arg = text.slice(cmd.length).trim();
        try {
          await modelsCommand(arg);
        } catch (err) {
          warn(`获取模型失败: ${err.message}`);
          prompt();
        }
        return;
      }
      if (cmd === "/new") {
        try {
          const session = await newSession();
          log(`新会话: ${session.id}${session.title ? ` · ${session.title}` : ""}`);
        } catch (err) {
          warn(`新建会话失败: ${err.message}`);
        }
        return prompt();
      }
      if (cmd === "/web") {
        openBrowser(`http://127.0.0.1:${port}/#/s/${state.sessionId}`);
        return prompt();
      }
      if (cmd === "/cancel") {
        await cancelRun();
        return prompt();
      }
      warn(`未知命令: ${cmd}（/help 查看帮助）`);
      return prompt();
    }

    if (state.busy) {
      await sendMessage(text);
      return;
    }

    await sendMessage(text);
  }

  rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
    historySize: 300,
    terminal: process.stdin.isTTY === true,
  });

  let session;
  try {
    session = await newSession();
  } catch (err) {
    if (!/auth/i.test(err.message)) die(`创建会话失败: ${err.message}`);
    if (!process.stdin.isTTY) die(`需要登录：请先运行 haoyuan login（${err.message}）`);
    try {
      await loginAt(port, rl);
      session = await newSession();
    } catch (loginErr) {
      die(`登录失败: ${loginErr.message}`);
    }
  }

  const mockHint = state.model.startsWith("mock/")
    ? `${C.dim}提示: 未配置模型 Key，当前使用本地 mock。运行 haoyuan config 进行全局配置，/models 切换模型。${C.reset}`
    : "";

  process.stdout.write(
    [
      "",
      `${C.bold}豪源 HaoYuan v${VERSION}${C.reset} · 终端对话`,
      `${C.dim}模型 ${state.model} · 工作区 ${process.cwd()}${C.reset}`,
      `${C.dim}会话 ${session.id} · /models 选模型 · /web 网页 · /help 帮助 · /exit 或 exit 退出${C.reset}`,
      mockHint,
      "",
    ]
      .filter(Boolean)
      .join("\n")
  );

  rl.on("line", (line) => {
    handleLine(line).catch((err) => {
      warn(err.message);
      prompt();
    });
  });

  rl.on("close", () => shutdown(0));

  const onSigint = async () => {
    if (state.busy) {
      await cancelRun();
      return;
    }
    shutdown(0);
  };
  rl.on("SIGINT", onSigint);
  process.on("SIGINT", onSigint);
  process.on("SIGTERM", () => shutdown(0));

  prompt();
}

function printVersion() {
  process.stdout.write(`${VERSION}\n`);
}

function npmRegistryArgs() {
  const registry = (process.env.HAOYUAN_NPM_REGISTRY || "").trim();
  return registry ? ["--registry", registry] : [];
}

function parseVersion(value) {
  return String(value || "")
    .trim()
    .replace(/^v/i, "")
    .split("-")[0]
    .split(".")
    .map((part) => {
      const n = Number.parseInt(part, 10);
      return Number.isFinite(n) ? n : 0;
    });
}

function compareVersions(a, b) {
  const pa = parseVersion(a);
  const pb = parseVersion(b);
  const len = Math.max(pa.length, pb.length);
  for (let i = 0; i < len; i += 1) {
    const x = pa[i] || 0;
    const y = pb[i] || 0;
    if (x !== y) return x < y ? -1 : 1;
  }
  return 0;
}

function npmCapture(args) {
  const full = [...args, ...npmRegistryArgs()];
  const useShell = IS_WIN && /\.(cmd|bat)$/i.test(NPM);
  const r = useShell
    ? spawnSync([NPM, ...full.map(shellQuote)].join(" "), { cwd: ROOT, encoding: "utf8", shell: true })
    : spawnSync(NPM, full, { cwd: ROOT, encoding: "utf8" });
  if (r.error) return { ok: false, error: r.error.message };
  if (r.status !== 0) {
    const detail = (r.stderr || r.stdout || "").trim();
    return { ok: false, error: detail || `npm 退出码 ${r.status}` };
  }
  return { ok: true, out: (r.stdout || "").trim() };
}

async function upgradeCommand() {
  log(`当前版本 v${VERSION}`);
  log("检查 npm 最新版本 ...");
  const result = npmCapture(["view", "haoyuan", "version"]);
  if (!result.ok) {
    fail(`检查最新版本失败: ${result.error}（可用 HAOYUAN_NPM_REGISTRY 指定 npm 源）`);
  }
  const latest = (result.out || "").split(/\s+/).filter(Boolean).pop() || "";
  if (!/^\d+\.\d+\.\d+/.test(latest)) {
    fail(`无法解析最新版本号: ${result.out || "(空)"}`);
  }
  log(`最新版本 v${latest}`);
  if (compareVersions(VERSION, latest) >= 0) {
    log("已是最新版本，无需升级。");
    return;
  }

  // Windows 下 npm 会重命名当前包目录；若服务正在运行或 cwd 在包内会 EBUSY，先停服务并在用户目录执行
  const port = readApiPort();
  if (port && (await healthyPort(port))) {
    stopLocalServer(port);
    await new Promise((resolve) => setTimeout(resolve, 800));
  }

  log(`开始升级 v${VERSION} → v${latest} ...`);
  const installArgs = ["install", "-g", `haoyuan@${latest}`, ...npmRegistryArgs()];
  let ok = run(NPM, installArgs, { lenient: true, cwd: os.homedir() });
  if (!ok && IS_WIN) {
    await new Promise((resolve) => setTimeout(resolve, 1500));
    ok = run(NPM, installArgs, { lenient: true, cwd: os.homedir() });
  }
  if (!ok) {
    fail(
      "升级失败：请完全退出正在运行的豪源（关闭所有 haoyuan 窗口/服务），在用户目录（如 C:\\Users\\你的用户名）下执行 npm install -g haoyuan@latest；权限不足请用管理员终端。"
    );
  }
  log(`升级完成：v${VERSION} → v${latest}`);
  log("请重新运行 haoyuan 以使用新版本。");
}

function printHelp() {
  process.stdout.write(
    [
      `豪源 HaoYuan v${VERSION}`,
      "",
      "用法: haoyuan [命令] [选项]",
      "",
      "命令:",
      "  haoyuan          终端对话（默认）",
      "  haoyuan web      启动服务并打开网页",
      "  haoyuan version  显示版本号",
      "  haoyuan config   全局配置文件（模型 Key 等），--open 直接打开编辑",
      "  haoyuan login    登录（账号保护开启时）",
      "  haoyuan logout   清除本地登录令牌",
      "  haoyuan setup    安装后端/前端依赖",
      "  haoyuan build    仅构建前端",
      "  haoyuan upgrade  升级到 npm 最新版本",
      "  haoyuan help     显示帮助",
      "",
      "选项:",
      "  -V, --version    显示版本号",
      "  --model x/y      指定模型（如 --model deepseek/deepseek-flash）",
      "  --no-open        web 启动后不打开浏览器",
      "  --no-build       setup 时跳过前端构建",
      "",
      "环境变量:",
      "  HAOYUAN_TOKEN    账号保护开启后的访问令牌",
      "  HAOYUAN_PORT     后端基准端口（默认 8030）",
      "",
    ].join("\n")
  );
}

const argv = process.argv.slice(2);
const command = argv[0] || "";
const flags = new Set(argv.slice(1));
const noOpen = flags.has("--no-open");
const noBuild = flags.has("--no-build");
let modelFlag = "";
const mi = argv.indexOf("--model");
if (mi >= 0 && argv[mi + 1] && !argv[mi + 1].startsWith("--")) {
  modelFlag = argv[mi + 1].trim();
}
const modelEq = argv.find((a) => a.startsWith("--model="));
if (modelEq) modelFlag = modelEq.slice(8).trim();

async function main() {
  if (command === "--version" || command === "-V" || command === "-v" || command === "version") {
    printVersion();
    return;
  }
  if (command === "--help" || command === "-h" || command === "help") {
    printHelp();
    return;
  }
  if (command === "" || command === "chat" || command === "--model") {
    await chat({ model: modelFlag });
    return;
  }
  if (command === "web" || command === "start" || command === "serve") {
    await web({ noOpen });
    return;
  }
  if (command === "setup") {
    setup({ build: !noBuild });
    return;
  }
  if (command === "login") {
    await loginCommand();
    return;
  }
  if (command === "logout") {
    logoutCommand();
    return;
  }
  if (command === "config") {
    configCommand({ open: flags.has("--open") });
    return;
  }
  if (command === "build") {
    buildFrontend();
    return;
  }
  if (command === "upgrade" || command === "update") {
    await upgradeCommand();
    return;
  }
  if (command === "postinstall") {
    postinstall();
    return;
  }
  fail(`未知命令: ${command}（运行 haoyuan help 查看用法）`);
}

main().catch((err) => fail(err.message));
