# Voice Clone — Windows installer (PowerShell)
# Requires Docker Desktop. For local Python use WSL or Git Bash: ./install --local

param(
    [switch]$Docker,
    [switch]$Local,
    [switch]$Force,
    [switch]$Help
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path

function Show-Help {
    Write-Host @"
Usage:
  .\install.ps1              Auto: Docker if available, else error with instructions
  .\install.ps1 -Docker      Build Docker image
  .\install.ps1 -Local       Print instructions for Git Bash / WSL local install

Then start:
  .\scripts\deploy.ps1
"@
}

if ($Help) { Show-Help; exit 0 }

function Test-Docker {
    try {
        docker info 2>$null | Out-Null
        return $?
    } catch { return $false }
}

function Test-DockerGpu {
    if (-not (Get-Command nvidia-smi -ErrorAction SilentlyContinue)) { return $false }
    try { nvidia-smi 2>$null | Out-Null } catch { return $false }
    $info = docker info 2>$null
    return $info -match 'nvidia|gpu'
}

if ($Local) {
    Write-Host "[+] For local Python on Windows, use Git Bash or WSL:"
    Write-Host "    ./install --local"
    Write-Host "    ./scripts/deploy.sh --local"
    exit 0
}

if (-not (Test-Docker)) {
    Write-Host "[x] Docker is not running. Install Docker Desktop and retry." -ForegroundColor Red
    Write-Host "    Or use Git Bash: ./install --local"
    exit 1
}

$gpu = Test-DockerGpu
if ($gpu) {
    Write-Host "[+] NVIDIA GPU detected — building CUDA image"
    docker compose -f "$Root\docker-compose.yml" -f "$Root\docker-compose.gpu.yml" build
} else {
    Write-Host "[+] Building CPU image"
    docker compose -f "$Root\docker-compose.yml" build
}

Write-Host "[+] Install complete. Start with: .\scripts\deploy.ps1"
