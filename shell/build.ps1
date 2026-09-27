<#
.SYNOPSIS
    Builds MIMI.exe - the native Windows shell for Mimi (WinForms + Microsoft Edge WebView2).

.DESCRIPTION
    1. Fetches the Microsoft.Web.WebView2 NuGet package (latest stable unless a version is
       pinned) into <root>\.tools\webview2sdk\<version>\ and caches it there. When nuget.org
       cannot be reached, the newest cached copy is used, so rebuilding works offline.
    2. Copies Microsoft.Web.WebView2.Core.dll and Microsoft.Web.WebView2.WinForms.dll
       (lib\net462) plus WebView2Loader.dll (runtimes\win-x64\native) into the app root.
    3. Compiles MimiShell.cs with the in-box .NET Framework C# compiler (C# 5) into
       <root>\MIMI.exe, embedding mimi.ico, splash.html and app.manifest.

    Needs only what ships with Windows 10/11: .NET Framework 4.8 and PowerShell 5.1.
    No Visual Studio, no SDKs, no admin rights. All paths derive from this script's location.

.PARAMETER WebView2Version
    NuGet package version to build against, e.g. 1.0.4191.47. Default: latest stable.

.PARAMETER Offline
    Do not touch the network; build against the newest SDK already in the cache.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File shell\build.ps1
#>
[CmdletBinding()]
param(
    [string]$WebView2Version = 'latest',
    [switch]$Offline
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # the PS 5.1 progress bar makes downloads crawl

$PackageId = 'Microsoft.Web.WebView2'
$ShellDir  = $PSScriptRoot
$Root      = Split-Path -Parent $ShellDir
$SdkCache  = Join-Path $Root '.tools\webview2sdk'
$Csc       = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$OutExe    = Join-Path $Root 'MIMI.exe'

$Source    = Join-Path $ShellDir 'MimiShell.cs'
$Manifest  = Join-Path $ShellDir 'app.manifest'
$IconFile  = Join-Path $ShellDir 'mimi.ico'
$Splash    = Join-Path $ShellDir 'splash.html'

function Write-Step([string]$Message) { Write-Host "==> $Message" -ForegroundColor Cyan }

function Get-CachedSdkVersions {
    if (-not (Test-Path $SdkCache)) { return @() }
    return @(Get-ChildItem -Path $SdkCache -Directory |
        Where-Object { $_.Name -match '^\d+(\.\d+){1,3}$' -and (Test-Path (Join-Path $_.FullName 'lib')) } |
        Sort-Object -Property @{ Expression = { [version]$_.Name } } -Descending |
        ForEach-Object { $_.Name })
}

function Resolve-LatestStableVersion {
    # The v2 feed answers /package/<id> with a redirect to the latest *stable* .nupkg.
    # Read the version from the redirect instead of downloading the package twice.
    $request = [System.Net.HttpWebRequest]::Create("https://www.nuget.org/api/v2/package/$PackageId")
    $request.AllowAutoRedirect = $false
    $request.Timeout = 20000
    $response = $request.GetResponse()
    try { $location = [string]$response.Headers['Location'] } finally { $response.Close() }
    if ($location -match 'packageVersion=([0-9A-Za-z.\-]+)') { return $Matches[1] }
    if ($location -match '\.(\d+\.\d+\.\d+(?:\.\d+)?)\.nupkg') { return $Matches[1] }
    throw "Could not work out the latest $PackageId version from nuget.org (redirect was '$location')."
}

function Get-WebView2Sdk([string]$Version) {
    $dir = Join-Path $SdkCache $Version
    if (Test-Path (Join-Path $dir 'lib')) {
        Write-Host "    using cached SDK $dir"
        return $dir
    }
    New-Item -ItemType Directory -Force -Path $SdkCache | Out-Null
    $nupkg = Join-Path $SdkCache ("{0}.{1}.nupkg" -f $PackageId.ToLowerInvariant(), $Version)
    if (-not (Test-Path $nupkg)) {
        $url = "https://www.nuget.org/api/v2/package/$PackageId/$Version"
        Write-Host "    downloading $url"
        $partial = "$nupkg.partial"
        Invoke-WebRequest -Uri $url -OutFile $partial -UseBasicParsing
        Move-Item -Force -Path $partial -Destination $nupkg
    }
    # A .nupkg is a zip. Expand-Archive in PS 5.1 insists on a .zip extension, so use the
    # framework API, extracting into a temp folder first so an interrupted run leaves no half SDK.
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $staging = "$dir.partial"
    if (Test-Path $staging) { Remove-Item -Recurse -Force $staging }
    [System.IO.Compression.ZipFile]::ExtractToDirectory($nupkg, $staging)
    Move-Item -Path $staging -Destination $dir
    Write-Host "    extracted to $dir"
    return $dir
}

function Copy-IfChanged([string]$From, [string]$To) {
    if (-not (Test-Path $From)) { throw "Expected file is missing from the WebView2 SDK: $From" }
    if (Test-Path $To) {
        $a = Get-FileHash -Algorithm SHA256 -Path $From
        $b = Get-FileHash -Algorithm SHA256 -Path $To
        if ($a.Hash -eq $b.Hash) { return }
    }
    Copy-Item -Force -Path $From -Destination $To
    Write-Host ("    copied {0}" -f (Split-Path -Leaf $To))
}

# ---------------------------------------------------------------------------------------------
Write-Step "Mimi shell build  (root: $Root)"

foreach ($required in @($Csc, $Source, $Manifest, $Splash)) {
    if (-not (Test-Path $required)) { throw "Required file not found: $required" }
}

# Everything compiled or embedded stays pure ASCII: other characters are written as \uXXXX escapes
# (C#, JavaScript) or HTML entities, so the result never depends on code pages or editor settings.
foreach ($file in @($Source, $Splash)) {
    $hits = @(Select-String -LiteralPath $file -Pattern '[^\x00-\x7F]' -Encoding UTF8)
    if ($hits.Count -gt 0) {
        throw ("{0} contains non-ASCII characters on line(s) {1}. Write them as \uXXXX escapes (C#/JS) or HTML entities." -f
            (Split-Path -Leaf $file), (($hits | ForEach-Object { $_.LineNumber } | Select-Object -Unique) -join ', '))
    }
}

# A running MIMI.exe locks the exe and the DLLs next to it.
$running = @(Get-Process -Name 'Mimi' -ErrorAction SilentlyContinue | Where-Object {
    try { $_.Path -eq $OutExe } catch { $false } })
if ($running.Count -gt 0) {
    throw ("MIMI.exe is running (pid {0}). Quit Mimi (tray icon > Quit Mimi) and build again." -f (($running | ForEach-Object { $_.Id }) -join ', '))
}

if (-not (Test-Path $IconFile)) {
    Write-Step 'mimi.ico not found - generating it'
    & (Join-Path $ShellDir 'make_icon.ps1') -OutFile $IconFile
}

# --- 1. WebView2 SDK -------------------------------------------------------------------------
Write-Step "Resolving $PackageId"
$version = $WebView2Version
if ($version -eq 'latest') {
    if ($Offline) {
        $version = $null
    } else {
        try {
            [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
            $version = Resolve-LatestStableVersion
            Write-Host "    latest stable is $version"
        } catch {
            Write-Warning "nuget.org is not reachable ($($_.Exception.Message)); falling back to the SDK cache."
            $version = $null
        }
    }
    if (-not $version) {
        $cached = @(Get-CachedSdkVersions)
        if ($cached.Count -eq 0) { throw "No cached WebView2 SDK in $SdkCache and nuget.org is not reachable." }
        $version = $cached[0]
        Write-Host "    using newest cached version $version"
    }
}
$sdkDir = Get-WebView2Sdk $version

# --- 2. Runtime DLLs next to MIMI.exe ---------------------------------------------------------
Write-Step 'Copying WebView2 assemblies into the app root'
$libDir = Join-Path $sdkDir 'lib\net462'
if (-not (Test-Path $libDir)) {
    # Older packages shipped net45 instead of net462.
    $fallback = Get-ChildItem -Path (Join-Path $sdkDir 'lib') -Directory |
        Where-Object { $_.Name -match '^net4\d+$' } | Sort-Object Name -Descending | Select-Object -First 1
    if (-not $fallback) { throw "No .NET Framework (net4x) assemblies found in $sdkDir\lib" }
    $libDir = $fallback.FullName
}
$coreDll     = Join-Path $Root 'Microsoft.Web.WebView2.Core.dll'
$winFormsDll = Join-Path $Root 'Microsoft.Web.WebView2.WinForms.dll'
Copy-IfChanged (Join-Path $libDir 'Microsoft.Web.WebView2.Core.dll')     $coreDll
Copy-IfChanged (Join-Path $libDir 'Microsoft.Web.WebView2.WinForms.dll') $winFormsDll
Copy-IfChanged (Join-Path $sdkDir 'runtimes\win-x64\native\WebView2Loader.dll') (Join-Path $Root 'WebView2Loader.dll')

# --- 3. Compile ---------------------------------------------------------------------------------
Write-Step 'Compiling MimiShell.cs'
# Compile into a temp folder and only then replace MIMI.exe, so a failed build never leaves a
# truncated exe behind.
$buildDir = Join-Path ([System.IO.Path]::GetTempPath()) ("mimi-shell-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $buildDir | Out-Null
$tempExe = Join-Path $buildDir 'MIMI.exe'
try {
    $cscArgs = @(
        '/nologo', '/noconfig',
        '/target:winexe', '/platform:x64', '/optimize+', '/debug-', '/warn:4',
        '/codepage:65001', '/utf8output',
        "/out:$tempExe",
        "/win32icon:$IconFile",
        "/win32manifest:$Manifest",
        "/resource:$IconFile,Mimi.Shell.mimi.ico",
        "/resource:$Splash,Mimi.Shell.splash.html",
        '/reference:System.dll',
        '/reference:System.Core.dll',
        '/reference:System.Drawing.dll',
        '/reference:System.Windows.Forms.dll',
        '/reference:System.Net.Http.dll',
        '/reference:System.Web.Extensions.dll',
        "/reference:$coreDll",
        "/reference:$winFormsDll",
        $Source
    )
    & $Csc @cscArgs
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $tempExe)) {
        throw "C# compilation failed (csc exit code $LASTEXITCODE). See the errors above."
    }
    Copy-Item -Force -Path $tempExe -Destination $OutExe
} finally {
    Remove-Item -Recurse -Force -Path $buildDir -ErrorAction SilentlyContinue
}

$info = Get-Item $OutExe
Write-Step ("Built {0}  ({1:N0} KB, WebView2 SDK {2})" -f $info.FullName, ($info.Length / 1KB), $version)
