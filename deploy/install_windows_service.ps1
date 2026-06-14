# Example Windows/NSSM installer template — edit placeholders before running.
# Placeholders: $Base (install dir), $Model, $Device, $Lang, $ServiceName
#
#requires -RunAsAdministrator
<#
  Installs electric-blue as a Windows service (NSSM).
  Run from an elevated PowerShell:

      .\install_windows_service.ps1
      .\install_windows_service.ps1 -FfmpegDir "C:\ffmpeg\bin"   # if ffmpeg isn't on system PATH

  Prereqs: Python 3.10+ on PATH, ffmpeg available (winget install Gyan.FFmpeg),
  and a recent NVIDIA driver (CUDA 12 runtime) if using -Device cuda.
  cuDNN/cuBLAS are pip-installed automatically when Device=cuda.
#>
[CmdletBinding()]
param(
  [string]$Base        = "C:\electric-blue",
  [string]$Model       = "large-v3",
  [string]$Device      = "cuda",
  [string]$Lang        = "en",
  [string]$FfmpegDir   = "",        # e.g. C:\ffmpeg\bin ; blank if ffmpeg is already on system PATH
  [string]$ServiceName = "ElectricBlue"
)

$ErrorActionPreference = "Stop"
Write-Host "==> Setting up $ServiceName in $Base" -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $Base | Out-Null

# 1. Python venv -------------------------------------------------------------
$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $py) { throw "Python not found on PATH. Install Python 3.10+ first." }
$venv      = Join-Path $Base "venv"
$venvPy    = Join-Path $venv "Scripts\python.exe"
$venvEntry = Join-Path $venv "Scripts\electric-blue.exe"
if (-not (Test-Path $venvPy)) {
  Write-Host "==> Creating venv"
  & $py -m venv $venv
}

# 2. Dependencies (+ CUDA libs if using a GPU) --------------------------------
Write-Host "==> Installing dependencies"
& $venvPy -m pip install --upgrade pip
& $venvPy -m pip install "electric-blue[local]"
if ($Device -eq "cuda") {
  & $venvPy -m pip install nvidia-cublas-cu12 nvidia-cudnn-cu12
}

# 3. NSSM --------------------------------------------------------------------
$nssm = Join-Path $Base "nssm.exe"
if (-not (Test-Path $nssm)) {
  Write-Host "==> Downloading NSSM"
  $zip = Join-Path $env:TEMP "nssm.zip"
  Invoke-WebRequest "https://nssm.cc/release/nssm-2.24.zip" -OutFile $zip
  $tmp = Join-Path $env:TEMP "nssm_extract"
  Expand-Archive $zip $tmp -Force
  Copy-Item (Join-Path $tmp "nssm-2.24\win64\nssm.exe") $nssm -Force
}

# 4. Build the service PATH (CTranslate2 must find the pip-installed CUDA DLLs)
$envPath = $env:Path
if ($Device -eq "cuda") {
  $nv = Join-Path $venv "Lib\site-packages\nvidia"
  $envPath = "$(Join-Path $nv 'cudnn\bin');$(Join-Path $nv 'cublas\bin');$envPath"
}
if ($FfmpegDir) { $envPath = "$FfmpegDir;$envPath" }

# 5. (Re)register the service ------------------------------------------------
Write-Host "==> Registering service"
& $nssm stop   $ServiceName 2>$null
& $nssm remove $ServiceName confirm 2>$null
& $nssm install $ServiceName $venvEntry
& $nssm set $ServiceName AppDirectory $Base
& $nssm set $ServiceName AppStdout    (Join-Path $Base "service.log")
& $nssm set $ServiceName AppStderr    (Join-Path $Base "service.err.log")
& $nssm set $ServiceName Start        SERVICE_AUTO_START

$envBlock = @(
  "TRANSCRIBE_BASE=$Base"
  "WHISPER_MODEL=$Model"
  "WHISPER_DEVICE=$Device"
  "WHISPER_LANG=$Lang"
  "PATH=$envPath"
) -join "`r`n"
& $nssm set $ServiceName AppEnvironmentExtra $envBlock

& $nssm start $ServiceName
Write-Host "==> $ServiceName is running. Drop files in $Base\inbox" -ForegroundColor Green
Write-Host "    Logs: $Base\service.log  |  manage with: nssm edit $ServiceName"
