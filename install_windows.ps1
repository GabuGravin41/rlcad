# RL CAD installer for Windows (PowerShell). Run from the rlcad folder:
#   powershell -ExecutionPolicy Bypass -File .\install_windows.ps1
#
# 1. creates .venv and installs RL CAD (and RL PCB from ..\rlpcb, so the PCB <-> CAD checks run)
# 2. installs the RL CAD workbench into FreeCAD (Mod\RLCAD) and writes %USERPROFILE%\.rlcad\config.json
# 3. adds the "rlcad" MCP server to Claude Desktop (keeps your other servers; backs the file up first)
# 4. runs RL CAD once on the example design
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here

Write-Host "== 1/4 Python environment" -ForegroundColor Cyan
function Find-FreeCADDir {
    foreach ($r in @("$env:ProgramFiles", "${env:ProgramFiles(x86)}", "$env:LOCALAPPDATA\Programs")) {
        if (-not $r) { continue }
        $d = Get-ChildItem -Path $r -Filter "FreeCAD*" -Directory -ErrorAction SilentlyContinue | Sort-Object Name -Descending | Select-Object -First 1
        if ($d) { return $d.FullName }
    }
    return $null
}
if (-not (Test-Path .\.venv\Scripts\python.exe)) {
    $made = $false
    $py = (Get-Command py -ErrorAction SilentlyContinue)
    if ($py) { py -3 -m venv .venv; $made = (Test-Path .\.venv\Scripts\python.exe) }
    if (-not $made) {
        $pyexe = Get-Command python -ErrorAction SilentlyContinue
        if ($pyexe -and ($pyexe.Source -notlike "*WindowsApps*")) { python -m venv .venv; $made = (Test-Path .\.venv\Scripts\python.exe) }
    }
    if (-not $made) {
        # no system Python: FreeCAD ships one (3.11), which build123d supports
        $fcd = Find-FreeCADDir
        if ($fcd -and (Test-Path "$fcd\bin\python.exe")) {
            Write-Host "Using FreeCAD's Python to create the environment: $fcd\bin\python.exe"
            & "$fcd\bin\python.exe" -m venv .venv
        }
    }
    if (-not (Test-Path .\.venv\Scripts\python.exe)) { throw "No Python found. Install Python 3.11+ from python.org and run again." }
}
$vpy = (Resolve-Path .\.venv\Scripts\python.exe).Path
& $vpy -m pip install --upgrade pip | Out-Null
& $vpy -m pip install -e ".[mcp,test]"
# optional: Embree ray casting makes the print audit ~30x faster; skipped quietly if no wheel for this Python
& $vpy -m pip install embreex 2>$null | Out-Null
$rlpcb = Join-Path (Split-Path $here -Parent) "rlpcb"
if (Test-Path (Join-Path $rlpcb "pyproject.toml")) {
    & $vpy -m pip install -e $rlpcb
    Write-Host "RL PCB installed from $rlpcb (PCB <-> CAD checks enabled)"
} else {
    Write-Host "RL PCB not found next to rlcad; PCB <-> CAD checks will use existing mech.json files only" -ForegroundColor Yellow
}

Write-Host "== 2/4 FreeCAD workbench" -ForegroundColor Cyan
$fccmd = $null
$roots = @("$env:ProgramFiles", "${env:ProgramFiles(x86)}", "$env:LOCALAPPDATA\Programs")
foreach ($r in $roots) {
    if (-not $r) { continue }
    $hit = Get-ChildItem -Path $r -Filter "FreeCAD*" -Directory -ErrorAction SilentlyContinue |
        ForEach-Object { Get-ChildItem -Path (Join-Path $_.FullName "bin") -Include "freecadcmd.exe","FreeCADCmd.exe" -Recurse -ErrorAction SilentlyContinue } |
        Sort-Object FullName -Descending | Select-Object -First 1
    if ($hit) { $fccmd = $hit.FullName; break }
}
$modDir = $null
if ($fccmd) {
    Write-Host "FreeCAD: $fccmd"
    $tmp = Join-Path $env:TEMP "rlcad_fcdir.py"
    Set-Content -Path $tmp -Value "import FreeCAD`nopen(r'$env:TEMP\rlcad_fcdir.txt','w').write(FreeCAD.getUserAppDataDir())"
    & $fccmd $tmp | Out-Null
    $ud = (Get-Content "$env:TEMP\rlcad_fcdir.txt" -ErrorAction SilentlyContinue)
    if ($ud) { $modDir = Join-Path $ud "Mod" }
}
if (-not $modDir) { $modDir = Join-Path $env:APPDATA "FreeCAD\Mod"; Write-Host "FreeCAD not found; using $modDir" -ForegroundColor Yellow }
New-Item -ItemType Directory -Force -Path $modDir | Out-Null
$dst = Join-Path $modDir "RLCAD"
if (Test-Path $dst) { Remove-Item -Recurse -Force $dst }
Copy-Item -Recurse -Force (Join-Path $here "rlcad\adapters\freecad\RLCAD") $dst
Write-Host "Workbench installed: $dst"

$cfgDir = Join-Path $env:USERPROFILE ".rlcad"
New-Item -ItemType Directory -Force -Path $cfgDir | Out-Null
$cfg = @{ python = $vpy; bridge_port = 49717; bridge_autostart = $true; freecadcmd = $fccmd }
$cfg | ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $cfgDir "config.json")
Write-Host "Config: $cfgDir\config.json"

Write-Host "== 3/4 Claude Desktop (MCP)" -ForegroundColor Cyan
$claudeCfg = Join-Path $env:APPDATA "Claude\claude_desktop_config.json"
$example = (Resolve-Path .\examples\f35_ducted_quad).Path
if (Test-Path $claudeCfg) {
    Copy-Item $claudeCfg "$claudeCfg.bak-rlcad" -Force
    $json = Get-Content $claudeCfg -Raw | ConvertFrom-Json
} else {
    New-Item -ItemType Directory -Force -Path (Split-Path $claudeCfg) | Out-Null
    $json = [pscustomobject]@{}
}
if (-not ($json.PSObject.Properties.Name -contains "mcpServers")) {
    $json | Add-Member -NotePropertyName mcpServers -NotePropertyValue ([pscustomobject]@{})
}
$entry = [pscustomobject]@{ command = $vpy; args = @("-m", "rlcad.agent.mcp_server"); env = [pscustomobject]@{ RLCAD_PROJECT = $example } }
if ($json.mcpServers.PSObject.Properties.Name -contains "rlcad") { $json.mcpServers.rlcad = $entry }
else { $json.mcpServers | Add-Member -NotePropertyName rlcad -NotePropertyValue $entry }
$json | ConvertTo-Json -Depth 10 | Set-Content -Encoding UTF8 $claudeCfg
Write-Host "Added 'rlcad' to $claudeCfg (backup: .bak-rlcad). Restart Claude Desktop to load it."

Write-Host "== 4/4 First run" -ForegroundColor Cyan
& $vpy -m rlcad integrate examples\f35_ducted_quad
Write-Host ""
Write-Host "Done. Open FreeCAD, switch to the 'RL CAD' workbench, 'Open design...' -> examples\f35_ducted_quad." -ForegroundColor Green
Write-Host "Edit column B of RLCAD_Params, then 'Sync'. Claude (rlcad MCP) can drive the same FreeCAD window."
