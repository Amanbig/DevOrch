<#
.SYNOPSIS
    DevOrch installer for Windows (also works with PowerShell 7 on Linux and macOS).

.DESCRIPTION
    Installs the `devorch` command in its own isolated environment, so it never touches your system Python.
    It picks the first available of: uv, pipx, or a private virtual environment (needs Python 3.10+). If none
    of those work it offers to install uv (which can download Python itself).

    It never needs administrator rights, prints every command it runs, and leaves ~\.devorch (your config and
    sessions) alone, even with -Uninstall. Read it before you run it; it is short.

    Install:
        irm https://raw.githubusercontent.com/Amanbig/DevOrch/main/install.ps1 | iex

    With options (a script block, because `| iex` cannot take parameters):
        & ([scriptblock]::Create((irm https://raw.githubusercontent.com/Amanbig/DevOrch/main/install.ps1))) -Version 0.5.4

    Or set environment variables first: DEVORCH_VERSION, DEVORCH_METHOD, DEVORCH_FROM, DEVORCH_YES=1.

.PARAMETER Version
    Install a specific version.
.PARAMETER Method
    auto (default), uv, pipx or venv.
.PARAMETER From
    Install from a wheel, sdist, URL or pip spec instead of PyPI (for testing a build).
.PARAMETER BinDir
    Where the `devorch` shim is created (venv method). Default: ~\.local\bin
.PARAMETER Yes
    Do not ask before installing uv.
.PARAMETER DryRun
    Show what would run and change nothing.
.PARAMETER Uninstall
    Remove DevOrch (keeps ~\.devorch).
#>
[CmdletBinding()]
param(
    [string]$Version = $env:DEVORCH_VERSION,
    [ValidateSet('auto', 'uv', 'pipx', 'venv')]
    [string]$Method = $(if ($env:DEVORCH_METHOD) { $env:DEVORCH_METHOD } else { 'auto' }),
    [string]$From = $env:DEVORCH_FROM,
    [string]$BinDir = $(if ($env:DEVORCH_BIN_DIR) { $env:DEVORCH_BIN_DIR } else { Join-Path $HOME '.local/bin' }),
    [switch]$Yes = ($env:DEVORCH_YES -eq '1'),
    [switch]$DryRun,
    [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'
$Package = 'devorch'
$OnWindows = ($PSVersionTable.PSEdition -eq 'Desktop') -or ($IsWindows -eq $true)
$ExeSuffix = if ($OnWindows) { '.exe' } else { '' }
$DataDir = if ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA 'devorch' } else { Join-Path $HOME '.local/share/devorch' }
$VenvDir = Join-Path $DataDir 'venv'
$VenvBin = Join-Path $VenvDir $(if ($OnWindows) { 'Scripts' } else { 'bin' })

function Say($Text) { Write-Host $Text }
function Info($Text) { Write-Host "==> $Text" }
function Warn($Text) { Write-Warning $Text }
# `throw`, not `exit`: when run as `irm ... | iex`, `exit` would close the user's own PowerShell window
function Die($Text) { throw "error: $Text" }
function Have($Name) { return [bool](Get-Command $Name -ErrorAction SilentlyContinue) }

# Print a command, then run it unless this is a dry run. Stops on a non-zero exit code.
function Run {
    param([string]$Exe, [string[]]$Arguments = @())
    Write-Host ("+ $Exe " + ($Arguments -join ' '))
    if ($DryRun) { return }
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { Die "'$Exe $($Arguments -join ' ')' failed with exit code $LASTEXITCODE" }
}

function Get-PackageSpec {
    if ($From) { return $From }
    if ($Version) { return "$Package==$Version" }
    return $Package
}

# A Python >= 3.10 that can create virtual environments. Returns @{Exe=..; Prefix=@(..)} or $null.
function Find-Python {
    $candidates = @(
        @{ Exe = 'py'; Prefix = @('-3') }, @{ Exe = 'python3'; Prefix = @() }, @{ Exe = 'python'; Prefix = @() }
    )
    foreach ($c in $candidates) {
        if (-not (Have $c.Exe)) { continue }
        try {
            & $c.Exe @($c.Prefix + @('-c', 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)')) 2>$null
            if ($LASTEXITCODE -ne 0) { continue }
            & $c.Exe @($c.Prefix + @('-c', 'import ensurepip, venv')) 2>$null
            if ($LASTEXITCODE -ne 0) { continue }
            return $c
        } catch { continue }  # e.g. the Microsoft Store python alias that cannot run
    }
    return $null
}

function Confirm-Action($Question) {
    if ($Yes) { return $true }
    if (-not [Environment]::UserInteractive -or [Console]::IsInputRedirected) { return $false }
    $answer = Read-Host "$Question [y/N]"
    return $answer -match '^(y|yes)$'
}

function Install-Uv {
    Info 'uv (a fast Python tool installer, which can also download Python) is not installed'
    if (-not (Confirm-Action 'Install uv now from https://astral.sh/uv?')) {
        Die 'no installer available. Install uv (https://docs.astral.sh/uv/), pipx, or Python 3.10+ and run this again, or re-run with -Yes to let me install uv.'
    }
    Write-Host '+ irm https://astral.sh/uv/install.ps1 | iex'
    if ($DryRun) { return }
    $env:UV_NO_MODIFY_PATH = '1'   # leave the PATH alone; advice is printed at the end
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    $env:PATH = (Join-Path $HOME '.local/bin') + [IO.Path]::PathSeparator + $env:PATH
    if (-not (Have 'uv')) { Die 'uv was installed but is not on PATH; open a new terminal and run this again' }
}

function Select-Method {
    if ($Method -ne 'auto') {
        switch ($Method) {
            'uv' { if (-not (Have 'uv')) { Die '-Method uv, but uv is not installed (https://docs.astral.sh/uv/)' } }
            'pipx' { if (-not (Have 'pipx')) { Die '-Method pipx, but pipx is not installed (https://pipx.pypa.io)' } }
            'venv' { if (-not (Find-Python)) { Die '-Method venv needs Python 3.10+ with the venv module' } }
        }
        return $Method
    }
    if (Have 'uv') { return 'uv' }
    if (Have 'pipx') { return 'pipx' }
    if (Find-Python) { return 'venv' }
    Install-Uv
    return 'uv'
}

function Get-CommandDir($Chosen) {
    switch ($Chosen) {
        'uv' { $d = (& uv tool dir --bin 2>$null); if ($d) { return "$d".Trim() } }
        'pipx' { $d = (& pipx environment --value PIPX_BIN_DIR 2>$null); if ($d) { return "$d".Trim() } }
    }
    return $BinDir
}

function Test-OnPath($Dir) {
    $sep = [IO.Path]::PathSeparator
    return (($env:PATH -split [regex]::Escape($sep)) | Where-Object { $_.TrimEnd('\', '/') -eq $Dir.TrimEnd('\', '/') }).Count -gt 0
}

function Invoke-Uninstall {
    $removed = $false
    if ((Have 'uv') -and ((& uv tool list 2>$null) -match "^$Package ")) { Run 'uv' @('tool', 'uninstall', $Package); $removed = $true }
    if ((Have 'pipx') -and ((& pipx list --short 2>$null) -match "^$Package ")) { Run 'pipx' @('uninstall', $Package); $removed = $true }
    if (Test-Path $VenvDir) {
        Write-Host "+ Remove-Item -Recurse -Force $VenvDir"
        if (-not $DryRun) { Remove-Item -Recurse -Force $VenvDir }
        foreach ($shim in @((Join-Path $BinDir 'devorch.cmd'), (Join-Path $BinDir 'devorch'))) {
            if (Test-Path $shim) {
                Write-Host "+ Remove-Item $shim"
                if (-not $DryRun) { Remove-Item -Force $shim }
            }
        }
        $removed = $true
    }
    if (-not $removed) {
        Say 'DevOrch was not installed by uv, pipx or this script; nothing to remove.'
        Say '(If you installed with pip, run: pip uninstall devorch)'
    } else {
        Info 'DevOrch removed'
    }
    Say 'Your config, sessions and memory in ~\.devorch were kept. Delete them with:  Remove-Item -Recurse -Force ~\.devorch'
}

function Invoke-Install {
    $chosen = Select-Method
    $spec = Get-PackageSpec
    Info "Installing $spec using $chosen"

    switch ($chosen) {
        'uv' { Run 'uv' @('tool', 'install', '--force', $spec) }
        'pipx' { Run 'pipx' @('install', '--force', $spec) }
        'venv' {
            $py = Find-Python
            if (-not $py) { $py = @{ Exe = 'python3'; Prefix = @() } }   # dry run after a skipped probe
            if (-not (Test-Path $VenvDir)) { Run $py.Exe @($py.Prefix + @('-m', 'venv', $VenvDir)) }
            $venvPython = Join-Path $VenvBin "python$ExeSuffix"
            Run $venvPython @('-m', 'pip', 'install', '--quiet', '--upgrade', 'pip')
            Run $venvPython @('-m', 'pip', 'install', '--upgrade', $spec)
            Write-Host "+ create a devorch launcher in $BinDir"
            if (-not $DryRun) {
                New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
                $target = Join-Path $VenvBin "devorch$ExeSuffix"
                if ($OnWindows) {
                    # symlinks need privileges on Windows, so use a tiny launcher script instead
                    Set-Content -Path (Join-Path $BinDir 'devorch.cmd') -Encoding ASCII -Value "@`"$target`" %*"
                } else {
                    $link = Join-Path $BinDir 'devorch'
                    if (Test-Path $link) { Remove-Item -Force $link }
                    New-Item -ItemType SymbolicLink -Path $link -Target $target | Out-Null
                }
            }
        }
    }

    if ($DryRun) { Info 'Dry run: nothing was changed'; return }

    $dir = Get-CommandDir $chosen
    $exe = Join-Path $dir "devorch$ExeSuffix"
    if (-not (Test-Path $exe)) { $exe = Join-Path $dir 'devorch.cmd' }
    if (-not (Test-Path $exe)) {
        $found = Get-Command devorch -ErrorAction SilentlyContinue
        if ($found) { $exe = $found.Source } else { Die "installed, but I could not find the devorch command (looked in $dir)" }
    }
    $installed = & $exe --version 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $installed) { Die "installed, but '$exe --version' failed" }
    Info "Installed: $installed  ($exe)"

    if (-not (Test-OnPath $dir)) {
        Warn "$dir is not on your PATH, so 'devorch' will not be found yet."
        Say 'Add it for your user, then open a new terminal:'
        Say "    [Environment]::SetEnvironmentVariable('Path', `"$dir;`" + [Environment]::GetEnvironmentVariable('Path', 'User'), 'User')"
    }
    Say ''
    Say 'Next:  devorch          start chatting (it walks you through choosing a provider and API key)'
    Say '       devorch doctor   check your setup'
    Say 'Upgrade later by running this installer again; remove with:  .\install.ps1 -Uninstall'
}

if ($Uninstall) { Invoke-Uninstall } else { Invoke-Install }
