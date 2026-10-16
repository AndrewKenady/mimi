<#
  Mimi setup: builds a complete Mimi tree from a fresh clone (Windows 10/11 x64).
  No administrator rights needed. Re-running is safe: finished steps are skipped and
  interrupted downloads resume.

    powershell -ExecutionPolicy Bypass -File scripts\setup.ps1                  # standard tier (~200 GB)
    powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 -Tier lite       # ~15 GB + a map region
    powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 -Tier lite -Region uk
    powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 -NoContent       # code + engines only

  Steps: portable Python (uv) -> Python packages -> engines -> app UI -> MIMI.exe ->
         content for the tier (models, offline library, maps, places, routing, addresses)

  Downloads are pinned and checked: uv and Node by the sha256 below, engines and content by
  manifests\*.json (scripts\fetch.py). Add or remove content later with scripts\content.py.
  Linux and macOS use scripts/install.sh instead; see docs\INSTALL.md.
#>
param(
  [ValidateSet('lite', 'standard')][string]$Tier = 'standard',
  [string]$Region = '',
  [switch]$NoContent, [switch]$NoRouting, [switch]$NoAddresses
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # Windows PowerShell 5.1's progress bar slows Invoke-WebRequest many times over
$Root = Split-Path -Parent $PSScriptRoot
$Tools = Join-Path $Root '.tools'
New-Item -ItemType Directory -Force $Tools, "$Tools\dl", "$Root\logs" | Out-Null
$env:UV_CACHE_DIR = "$Tools\uv-cache"; $env:UV_PYTHON_INSTALL_DIR = "$Tools\pythons"

# Pinned tools (update version and hash together; hashes are of the release zips).
$UvVersion = '0.11.32'
$UvSha256 = 'acfde570451cfdb8689fa159a138ee805ba4e241c466432750302c86254b0984'
$NodeVersion = 'v22.23.3'
$NodeSha256 = '2b0ff57b049cda1bbcea2240eec20467018713c1efe1f7360c2681859b90ed71'

function Step($t) { Write-Host "`n== $t" -ForegroundColor Cyan }
# $ErrorActionPreference doesn't cover native programs: stop on their failures explicitly.
function Check($what) { if ($LASTEXITCODE -ne 0) { throw "$what failed (exit code $LASTEXITCODE). Fix the error above and run setup again." } }
function Get-Verified($url, $file, $sha256) {
  if (-not (Test-Path $file)) { Invoke-WebRequest $url -OutFile $file }
  $got = (Get-FileHash $file -Algorithm SHA256).Hash.ToLower()
  if ($got -ne $sha256) { Remove-Item $file -Force; throw "$url failed its checksum (got $got). Run setup again." }
}

Step "uv $UvVersion (Python manager)"
if (-not (Test-Path "$Tools\uv\uv.exe")) {
  Get-Verified "https://github.com/astral-sh/uv/releases/download/$UvVersion/uv-x86_64-pc-windows-msvc.zip" "$Tools\dl\uv-$UvVersion.zip" $UvSha256
  Expand-Archive "$Tools\dl\uv-$UvVersion.zip" "$Tools\uv" -Force
}
$uv = "$Tools\uv\uv.exe"

Step 'Portable Python 3.12'
if (-not (Test-Path "$Root\python\python.exe")) {
  & $uv python install 3.12; Check 'uv python install'
  $src = Get-ChildItem "$Tools\pythons" -Directory | Where-Object Name -like 'cpython-3.12*' | Select-Object -First 1
  Copy-Item $src.FullName "$Root\python" -Recurse
  Get-ChildItem "$Root\python" -Recurse -Filter EXTERNALLY-MANAGED | Remove-Item -Force
}
$py = "$Root\python\python.exe"

Step 'Python packages'
# Core's dependencies straight from core\pyproject.toml (Mimi runs from core\, nothing to build).
& $uv pip install --python $py -r "$Root\core\pyproject.toml" --extra dev 'pyvalhalla>=3.9,<4' 'osmium>=4,<5'; Check 'Installing Python packages'

Step 'Engines (llama.cpp, kiwix-tools, aria2, pmtiles)'
& $py "$Root\scripts\fetch.py" --only runtimes; Check 'Downloading engines'

Step "Node.js $NodeVersion (portable) + app UI"
if (-not (Test-Path "$Tools\node\node.exe")) {
  Get-Verified "https://nodejs.org/dist/$NodeVersion/node-$NodeVersion-win-x64.zip" "$Tools\dl\node-$NodeVersion.zip" $NodeSha256
  if (Test-Path "$Tools\node-$NodeVersion-win-x64") { Remove-Item "$Tools\node-$NodeVersion-win-x64" -Recurse -Force }
  tar.exe -xf "$Tools\dl\node-$NodeVersion.zip" -C $Tools; Check 'Unpacking Node.js'
  Rename-Item "$Tools\node-$NodeVersion-win-x64" 'node'
}
$env:PATH = "$Tools\node;$env:PATH"
Push-Location "$Root\ui"
try {
  npm install --no-audit --no-fund; Check 'npm install'
  npm run build; Check 'Building the app UI'
} finally { Pop-Location }

Step 'MIMI.exe (native shell)'
& powershell -ExecutionPolicy Bypass -File "$Root\shell\build.ps1"
if ($LASTEXITCODE -ne 0) { Write-Host 'MIMI.exe did not build (see above); Mimi still runs with: cd core; ..\python\python.exe -m mimi serve' -ForegroundColor Yellow }

if (-not $NoContent) {
  Step "Content: $Tier tier (resumable; scripts\content.py status shows progress)"
  $contentArgs = @('add', $Tier, '--yes')
  if ($Region) { $contentArgs += @('--region', $Region) }
  $skip = @()
  if ($NoRouting) { $skip += 'routing' }
  if ($NoAddresses) { $skip += 'addresses' }
  if ($skip.Count) { $contentArgs += @('--skip') + $skip }
  & $py "$Root\scripts\content.py" @contentArgs
  if ($LASTEXITCODE -ne 0) {
    Write-Host "`nSome content didn't finish (see above). Run setup again, or scripts\content.py add $Tier, to resume." -ForegroundColor Yellow
  }
}

Write-Host "`nMIMI is ready. Double-click MIMI.exe (or run: cd core; ..\python\python.exe -m mimi serve)." -ForegroundColor Green
