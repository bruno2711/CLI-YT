#!/usr/bin/env node
require('dotenv').config();

const CLIENT_ID = process.env.GOOGLE_CLIENT_ID;
const CLIENT_SECRET = process.env.GOOGLE_CLIENT_SECRET;

const { execSync, spawn } = require("child_process");
const path = require("path");
const fs = require("fs");

// O diretório do pacote instalado pelo NPX no cache do usuário
const packageDir = path.join(__dirname, "..");
const venvDir = path.join(packageDir, ".venv");
const isWindows = process.platform === "win32";

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

  if (!fs.existsSync(venvDir)) {
    console.log("⚙️  Criando ambiente virtual Python...");
    execSync(`${pythonCmd} -m venv "${venvDir}"`, { stdio: "inherit" });
  }

  const reqFile = path.join(packageDir, "requirements.txt");
  if (fs.existsSync(reqFile)) {
    console.log("📦 Instalando dependências no ambiente isolado...");
    execSync(`"${pipExecutable}" install -q -r "${reqFile}"`, { stdio: "inherit" });
  }
}

function runPlayer() {
  const mainPy = path.join(packageDir, "main.py");

  // Roda usando obrigatoriamente o python.exe do .venv
  const child = spawn(pythonExecutable, [mainPy], {
    stdio: "inherit",
    cwd: process.cwd(), // Permite salvar token.json na pasta de execução do usuário
    env: {
      ...process.env,
      GOOGLE_CLIENT_ID: CLIENT_ID,
      GOOGLE_CLIENT_SECRET: CLIENT_SECRET,
    },
  });

  child.on("exit", (code) => {
    process.exit(code || 0);
  });
}

checkPython();
setupVenv();
runPlayer();