# Tapecut — Copyright (C) 2025-2026 Teodora Vuković (Teodora Vukovic)
# Licensed under the GNU Affero General Public License v3 or later.
# This program comes with ABSOLUTELY NO WARRANTY; see LICENSE for details.
#
# Install or update Tapecut on Windows 10/11. In PowerShell:
#
#   irm https://raw.githubusercontent.com/bravethea/tapecut/main/scripts/install.ps1 | iex
#
# Installs Git, ffmpeg and Python 3.13 with winget, puts the code in
# ~\Tapecut\app, builds its Python environment, and adds Tapecut to the Start
# menu and the desktop. Running it again updates everything in place. Your
# transcripts and settings in ~\Tapecut are never touched.
#
# $env:TAPECUT_DIR overrides where the code goes.

# Everything runs inside one script block: under `irm | iex`, `exit` would
# close the user's PowerShell window, so errors are thrown instead.
& {
    $ErrorActionPreference = 'Stop'
    $Repo = 'https://github.com/bravethea/tapecut.git'
    $Dir  = if ($env:TAPECUT_DIR) { $env:TAPECUT_DIR } else { Join-Path $HOME 'Tapecut\app' }

    function Say([string]$Text) { Write-Host "`n$Text" -ForegroundColor Cyan }

    # Native programs report failure through $LASTEXITCODE, not exceptions.
    function Run {
        & $args[0] @($args | Select-Object -Skip 1)
        if ($LASTEXITCODE -ne 0) { throw "Failed: $($args -join ' ')" }
    }

    function Refresh-Path {
        $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                    [Environment]::GetEnvironmentVariable('Path', 'User')
    }

    function Ensure([string]$Command, [string]$WingetId) {
        if (Get-Command $Command -ErrorAction SilentlyContinue) { return }
        Write-Host "Installing $WingetId…"
        Run winget install --id $WingetId --exact --silent `
            --accept-source-agreements --accept-package-agreements
        Refresh-Path
    }

    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw 'Tapecut needs winget. Install "App Installer" from the Microsoft Store, then run this again.'
    }

    Say 'Installing Git, ffmpeg and Python 3.13 (winget)…'
    Ensure git 'Git.Git'
    Ensure ffmpeg 'Gyan.FFmpeg'
    $Python = $null
    if (Get-Command py -ErrorAction SilentlyContinue) {
        try { $Python = (& py -3.13 -c 'import sys; print(sys.executable)' 2>$null) } catch { }
        if ($LASTEXITCODE -ne 0) { $Python = $null }
    }
    if (-not $Python) {
        Run winget install --id Python.Python.3.13 --exact --silent `
            --accept-source-agreements --accept-package-agreements
        Refresh-Path
        $Python = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'
    }
    if (-not (Test-Path $Python)) { throw "Couldn't find Python 3.13 (looked for $Python)." }

    if (Test-Path (Join-Path $Dir '.git')) {
        Say "Updating Tapecut in $Dir…"
        & git -C $Dir pull --ff-only
        if ($LASTEXITCODE -ne 0) {
            throw "Couldn't update $Dir - it has local changes. Commit or discard them and try again."
        }
    } elseif ((Test-Path $Dir) -and (Get-ChildItem $Dir -Force | Select-Object -First 1)) {
        throw "$Dir already exists and isn't a Tapecut checkout. Move it, or set `$env:TAPECUT_DIR to install elsewhere."
    } else {
        Say "Downloading Tapecut to $Dir…"
        New-Item -ItemType Directory -Force -Path (Split-Path $Dir -Parent) | Out-Null
        Run git clone --depth 1 $Repo $Dir
    }

    Say "Installing Tapecut's Python packages - a few GB, this takes several minutes…"
    $VenvPython = Join-Path $Dir 'venv\Scripts\python.exe'
    if (-not (Test-Path $VenvPython)) { Run $Python -m venv (Join-Path $Dir 'venv') }
    Run $VenvPython -m pip install --quiet --upgrade pip
    Run $VenvPython -m pip install --quiet -r (Join-Path $Dir 'requirements.txt')

    Say 'Adding Tapecut to the Start menu and desktop…'
    $Icon = Join-Path $HOME 'Tapecut\Tapecut.ico'
    & $VenvPython (Join-Path $Dir 'scripts\app_icon.py') $Icon
    if ($LASTEXITCODE -ne 0) { $Icon = $null }      # a plain icon is fine
    $Launcher = Join-Path $Dir 'scripts\tapecut-launch.ps1'
    $Shell = New-Object -ComObject WScript.Shell
    foreach ($Folder in @([Environment]::GetFolderPath('Programs'),
                          [Environment]::GetFolderPath('Desktop'))) {
        $Link = $Shell.CreateShortcut((Join-Path $Folder 'Tapecut.lnk'))
        $Link.TargetPath       = 'powershell.exe'
        $Link.Arguments        = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Launcher`""
        $Link.WorkingDirectory = $Dir
        if ($Icon) { $Link.IconLocation = $Icon }
        $Link.WindowStyle      = 7          # start minimised: no console flash
        $Link.Description      = 'Edit audio and video by editing the transcript'
        $Link.Save()
    }

    Say 'Done.'
    Write-Host @"
Open Tapecut from the Start menu or the desktop. The first transcription
downloads the Whisper model (~1.6 GB) once; after that everything runs offline
on this computer.

To update later, run the same install command again.
"@
}
