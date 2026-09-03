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

function checkPython() {
  try {
    const cmd = isWindows ? "where python" : "which python3 || which python";
    execSync(cmd, { stdio: "ignore" });
  } catch (e) {
    console.error("❌ Erro: Python 3 não foi encontrado no sistema.");
    console.error("Por favor, instale o Python 3 para executar esta aplicação.");
    process.exit(1);
  }
}

function setupVenv() {
  if (!fs.existsSync(venvDir)) {
    console.log("⚙️  Criando ambiente virtual Python na primeira execução...");
    const pythonCmd = isWindows ? "python" : "python3";
    execSync(`${pythonCmd} -m venv "${venvDir}"`, { stdio: "inherit" });
  }

  const reqFile = path.join(projectRoot, "requirements.txt");
  if (fs.existsSync(reqFile)) {
    console.log("📦 Verificando/Instalando dependências Python...");
    execSync(`"${pipExecutable}" install -q -r "${reqFile}"`, { stdio: "inherit" });
  }
}

function runPlayer() {
  const mainPy = path.join(projectRoot, "main.py");
  
  // Executa o main.py passando o controle de E/S completo do terminal para a TUI
  const child = spawn(pythonExecutable, [mainPy], {
    stdio: "inherit",
    cwd: projectRoot,
  });

  child.on("exit", (code) => {
    process.exit(code || 0);
  });
}

// Execução
checkPython();
setupVenv();
runPlayer();
