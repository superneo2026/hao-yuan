#!/usr/bin/env node
"use strict";

const { spawn, spawnSync } = require("child_process");
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const IS_WIN = process.platform === "win32";
const NPM = IS_WIN ? "npm.cmd" : "npm";
const VENV = path.join(ROOT, "api", "env1");
const PYTHON = IS_WIN
  ? path.join(VENV, "Scripts", "python.exe")
  : path.join(VENV, "bin", "python");
const WEB = path.join(ROOT, "web");
const API = path.join(ROOT, "api");

function log(msg) {
  process.stdout.write(`[HaoYuan] ${msg}\n`);
}

function fail(msg) {
  process.stderr.write(`[HaoYuan] ${msg}\n`);
  process.exit(1);
}

function run(cmd, args, opts = {}) {
  log(`${path.basename(cmd)} ${args.join(" ")}`);
  const r = spawnSync(cmd, args, { stdio: "inherit", cwd: ROOT, ...opts });
  if (r.error) fail(r.error.message);
  if (r.status !== 0) process.exit(r.status || 1);
}

function findPython() {
  const candidates = IS_WIN ? ["python", "py"] : ["python3", "python"];
  for (const py of candidates) {
    const r = spawnSync(py, ["--version"], { stdio: "ignore" });
    if (!r.error && r.status === 0) return py;
  }
  fail("未找到 Python 3.10+，请先安装 Python 后再运行。");
}

function ensureVenv() {
  if (fs.existsSync(PYTHON)) return;
  log("创建 Python 虚拟环境 api/env1 ...");
  run(findPython(), ["-m", "venv", VENV]);
}

function installBackend() {
  ensureVenv();
  run(PYTHON, ["-m", "pip", "install", "--upgrade", "pip"]);
  run(PYTHON, ["-m", "pip", "install", "-r", path.join(API, "requirements.txt")]);
}

function installFrontend() {
  if (!fs.existsSync(path.join(WEB, "node_modules"))) {
    log("安装前端依赖 ...");
    run(NPM, ["install", "--no-audit", "--no-fund"], { cwd: WEB });
  }
}

function buildFrontend() {
  installFrontend();
  log("构建前端 ...");
  run(NPM, ["run", "build"], { cwd: WEB });
}

function setup({ build = true } = {}) {
  installBackend();
  if (build) buildFrontend();
  else installFrontend();
}

function start() {
  if (!fs.existsSync(PYTHON)) setup({ build: true });
  if (!fs.existsSync(path.join(WEB, "dist", "index.html"))) buildFrontend();
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
}

const command = process.argv[2] || "start";

switch (command) {
  case "start":
    start();
    break;
  case "setup":
    setup({ build: !process.argv.includes("--no-build") });
    break;
  case "build":
    buildFrontend();
    break;
  case "help":
  case "-h":
  case "--help":
    process.stdout.write(
      [
        "用法: haoyuan [command]",
        "",
        "命令:",
        "  start   安装（如需）+ 构建前端 + 启动服务（默认）",
        "  setup   安装后端/前端依赖并构建前端",
        "  build   仅构建前端",
        "  help    显示帮助",
        "",
      ].join("\n")
    );
    break;
  default:
    fail(`未知命令: ${command}（运行 haoyuan help 查看用法）`);
}
