# Tapecut — Copyright (C) 2025-2026 Teodora Vuković (Teodora Vukovic)
# Licensed under the GNU Affero General Public License v3 or later.
# This program comes with ABSOLUTELY NO WARRANTY; see LICENSE for details.
#
# Windows launcher — what the Start menu and desktop shortcuts run (install.ps1
# makes them). Starts the server if nothing is answering yet, then opens the
# page in the default browser. The Windows counterpart of the Tapecut.app that
# make-app.sh builds.

$Project = Split-Path $PSScriptRoot -Parent
$Url     = 'http://127.0.0.1:8756'
$LogDir  = Join-Path $HOME 'Tapecut\logs'

function Test-Up {
    try { Invoke-WebRequest -Uri "$Url/" -UseBasicParsing -TimeoutSec 1 | Out-Null; $true }
    catch { $false }
}

function Fail([string]$Message) {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show($Message, "Tapecut couldn't start", 'OK', 'Error') | Out-Null
    exit 1
}

if (-not (Test-Up)) {
    $Python = Join-Path $Project 'venv\Scripts\python.exe'
    if (-not (Test-Path $Python)) {
        Fail "No Tapecut installation at $Project. Run the installer again."
    }
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    # Re-read PATH: a shortcut started by Explorer may predate the installer
    # adding ffmpeg, and Explorer only picks up PATH changes after sign-in.
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [Environment]::GetEnvironmentVariable('Path', 'User')
    # Windows' default text encoding isn't UTF-8; transcripts are.
    $env:PYTHONUTF8 = '1'
    $env:PYTHONUNBUFFERED = '1'
    # Hidden and detached: the server outlives this script. Each start
    # replaces the previous logs.
    Start-Process -FilePath $Python -ArgumentList '-m', 'web.server' `
        -WorkingDirectory $Project -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $LogDir 'server.log') `
        -RedirectStandardError  (Join-Path $LogDir 'server.err.log')
    # First start after install is slow while Windows scans the new files.
    for ($i = 0; $i -lt 120 -and -not (Test-Up); $i++) { Start-Sleep -Milliseconds 500 }
    if (-not (Test-Up)) {
        Fail "The server didn't answer within a minute. Details are in $LogDir\server.err.log."
    }
}

Start-Process $Url
