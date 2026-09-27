<#
  Mimi setup: builds a complete Mimi tree from a fresh clone (Windows 10/11 x64).
  No administrator rights needed. Re-running is safe.

    powershell -ExecutionPolicy Bypass -File scripts\setup.ps1            # everything
    powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 -NoContent # code + runtimes only

  Steps: portable Python (uv) -> Python packages -> runtimes -> models ->
         offline library -> maps (+ geodata, routing) -> app UI -> MIMI.exe
#>
param([switch]$NoContent, [switch]$NoRouting)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Tools = Join-Path $Root '.tools'
New-Item -ItemType Directory -Force $Tools, "$Tools\dl", "$Root\logs" | Out-Null
$env:UV_CACHE_DIR = "$Tools\uv-cache"; $env:UV_PYTHON_INSTALL_DIR = "$Tools\pythons"

function Step($t) { Write-Host "`n== $t" -ForegroundColor Cyan }

Step 'uv (Python manager)'
if (-not (Test-Path "$Tools\uv\uv.exe")) {
  Invoke-WebRequest 'https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip' -OutFile "$Tools\dl\uv.zip"
  Expand-Archive "$Tools\dl\uv.zip" "$Tools\uv" -Force
}
$uv = "$Tools\uv\uv.exe"

Step 'Portable Python 3.12'
if (-not (Test-Path "$Root\python\python.exe")) {
  & $uv python install 3.12
  $src = Get-ChildItem "$Tools\pythons" -Directory | Where-Object Name -like 'cpython-3.12*' | Select-Object -First 1
  Copy-Item $src.FullName "$Root\python" -Recurse
  Get-ChildItem "$Root\python" -Recurse -Filter EXTERNALLY-MANAGED | Remove-Item -Force
}
$py = "$Root\python\python.exe"

Step 'Python packages'
& $uv pip install --python $py -e "$Root\core[dev]" pyvalhalla osmium

Step 'Runtimes (llama.cpp, kiwix-tools, aria2, pmtiles)'
& $py "$Root\scripts\fetch.py" --only runtimes

if (-not $NoContent) {
  Step 'Models, offline library and maps (large: ~190 GB, resumable)'
  & $py "$Root\scripts\fetch.py" --only models zim maps
  Step 'Places and Wikipedia geotags'
  & $py "$Root\scripts\build_geodata.py"
  if (-not $NoRouting) {
    Step 'Offline routing graph (a few hours for US + Canada)'
    & $py "$Root\scripts\build_routing.py"
  }
}

Step 'Node.js (portable) + app UI'
if (-not (Test-Path "$Tools\node\node.exe")) {
  $idx = Invoke-RestMethod 'https://nodejs.org/dist/index.json'
  $v = ($idx | Where-Object { $_.lts } | Select-Object -First 1).version
  Invoke-WebRequest "https://nodejs.org/dist/$v/node-$v-win-x64.zip" -OutFile "$Tools\dl\node.zip"
  tar.exe -xf "$Tools\dl\node.zip" -C $Tools
  Rename-Item "$Tools\node-$v-win-x64" 'node'
}
$env:PATH = "$Tools\node;$env:PATH"
Push-Location "$Root\ui"; npm install --no-audit --no-fund; npm run build; Pop-Location

Step 'MIMI.exe (native shell)'
& powershell -ExecutionPolicy Bypass -File "$Root\shell\build.ps1"

Write-Host "`nMIMI is ready. Double-click MIMI.exe (or run: cd core; ..\python\python.exe -m mimi serve)." -ForegroundColor Green
