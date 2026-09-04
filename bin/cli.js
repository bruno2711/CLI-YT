#!/usr/bin/env node

const { execSync, spawn } = require("child_process");
const path = require("path");
const fs = require("fs");
const os = require("os");

// Carrega o arquivo .env da pasta atual se existir
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

  // Passa o process.env original sem criar chaves vazias
  const child = spawn(pythonExecutable, [mainPy], {
    stdio: "inherit",
    cwd: process.cwd(),
    env: process.env,
  });

  child.on("exit", (code) => {
    process.exit(code || 0);
  });
}

checkPython();
setupVenv();
runPlayer();