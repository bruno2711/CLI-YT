#!/usr/bin/env node

const { execSync, spawn } = require("child_process");
const path = require("path");
const fs = require("fs");

const projectRoot = path.join(__dirname, "..");
const venvDir = path.join(projectRoot, ".venv");
const isWindows = process.platform === "win32";

const pythonExecutable = isWindows
  ? path.join(venvDir, "Scripts", "python.exe")
  : path.join(venvDir, "bin", "python");

const pipExecutable = isWindows
  ? path.join(venvDir, "Scripts", "pip.exe")
  : path.join(venvDir, "bin", "pip");

// Insira aqui suas credenciais do Google OAuth ou leia de um arquivo local .env durante a build
const CLIENT_ID = process.env.GOOGLE_CLIENT_ID || "SEU_CLIENT_ID.apps.googleusercontent.com";
const CLIENT_SECRET = process.env.GOOGLE_CLIENT_SECRET || "GOCSPX-SEU_CLIENT_SECRET";

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
  if (!fs.existsSync(venvDir)) {
    console.log("⚙️  Criando ambiente virtual Python...");
    const pythonCmd = isWindows ? "python" : "python3";
    execSync(`${pythonCmd} -m venv "${venvDir}"`, { stdio: "inherit" });
  }

  const reqFile = path.join(projectRoot, "requirements.txt");
  if (fs.existsSync(reqFile)) {
    console.log("📦 Instalando dependências...");
    execSync(`"${pipExecutable}" install -q -r "${reqFile}"`, { stdio: "inherit" });
  }
}

function runPlayer() {
  const mainPy = path.join(projectRoot, "main.py");

  const child = spawn(pythonExecutable, [mainPy], {
    stdio: "inherit",
    cwd: process.cwd(), // Executa no diretório atual do usuário para salvar o token.json localmente
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
