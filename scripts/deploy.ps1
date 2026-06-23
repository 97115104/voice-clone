# Voice Clone — Windows deploy (PowerShell + Docker Desktop)

param(
    [switch]$Stop,
    [switch]$Detach,
    [switch]$NoBuild,
    [switch]$Help
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Port = if ($env:PORT) { $env:PORT } else { "8004" }

if ($Help) {
    Write-Host "Usage: .\scripts\deploy.ps1 [-Stop] [-Detach] [-NoBuild]"
    exit 0
}

function Test-DockerGpu {
    if (-not (Get-Command nvidia-smi -ErrorAction SilentlyContinue)) { return $false }
    try { nvidia-smi 2>$null | Out-Null } catch { return $false }
    $info = docker info 2>$null
    return $info -match 'nvidia|gpu'
}

docker info 2>$null | Out-Null
if (-not $?) { Write-Host "[x] Docker is not running"; exit 1 }

$files = @("-f", "$Root\docker-compose.yml")
if (Test-DockerGpu) {
    Write-Host "[+] Using NVIDIA GPU"
    $files += "-f", "$Root\docker-compose.gpu.yml"
} else {
    Write-Host "[+] Using CPU"
}

if ($Stop) {
    docker compose @files down 2>$null
    docker compose -f "$Root\docker-compose.yml" down 2>$null
    Write-Host "[+] Stopped"
    exit 0
}

$env:PORT = $Port
$upArgs = @("compose") + $files + @("up")
if (-not $NoBuild) { docker compose @files build }
if ($Detach) {
    docker compose @files up -d
    Start-Process "http://127.0.0.1:$Port"
    Write-Host "[+] Running at http://127.0.0.1:$Port"
} else {
    Write-Host "[+] Starting http://127.0.0.1:$Port (Ctrl+C to stop)"
    Start-Job { param($u,$f,$p) Start-Sleep 3; Start-Process "http://127.0.0.1:$p" } -ArgumentList $upArgs,$files,$Port | Out-Null
    docker compose @files up
}
