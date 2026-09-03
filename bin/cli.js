#!/usr/bin/env node

const { execSync, spawn } = require("child_process");
const path = require("path");
const fs = require("fs");
const os = require("os");

// Carrega o arquivo .env da pasta atual
require("dotenv").config({ path: path.join(process.cwd(), ".env") });

const packageDir = path.join(__dirname, "..");
const isWindows = process.platform === "win32";

// Ambiente virtual isolado no Temp do usuário
const venvDir = path.join(os.tmpdir(), "cli-yt-venv");

const pythonExecutable = isWindows
  ? path.join(venvDir, "Scripts", "python.exe")
  : path.join(venvDir, "bin", "python");

const pipExecutable = isWindows
  ? path.join(venvDir, "Scripts", "pip.exe")
  : path.join(venvDir, "bin", "pip");

// Tenta pegar do .env ou do ambiente do sistema
const CLIENT_ID = process.env.GOOGLE_CLIENT_ID;
const CLIENT_SECRET = process.env.GOOGLE_CLIENT_SECRET;

function checkPython() {
  try {
    const cmd = isWindows ? "where python" : "which python3 || which python";
    execSync(cmd, { stdio: "ignore" });
  } catch (e) {
    console.error("❌ Erro: Python 3 não foi encontrado no sistema.");
    process.exit(1);
  }
}

function setupVenv() {
  const pythonCmd = isWindows ? "python" : "python3";

  if (!fs.existsSync(pythonExecutable)) {
    console.log("⚙️  Criando ambiente virtual Python isolado...");
    execSync(`${pythonCmd} -m venv "${venvDir}"`, { stdio: "inherit" });
  }

  const reqFile = path.join(packageDir, "requirements.txt");
  if (fs.existsSync(reqFile)) {
    console.log("📦 Verificando/Instalando dependências...");
    execSync(`"${pipExecutable}" install -q -r "${reqFile}"`, { stdio: "inherit" });
  }
}

function runPlayer() {
  const mainPy = path.join(packageDir, "main.py");

  // Repassa o ambiente e garante as chaves no process.env
  const child = spawn(pythonExecutable, [mainPy], {
    stdio: "inherit",
    cwd: process.cwd(),
    env: {
      ...process.env,
      GOOGLE_CLIENT_ID: CLIENT_ID || "",
      GOOGLE_CLIENT_SECRET: CLIENT_SECRET || "",
    },
  });

  child.on("exit", (code) => {
    process.exit(code || 0);
  });
}

checkPython();
setupVenv();
runPlayer();