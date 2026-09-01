param(
    [string]$PythonExe = "python",
    [string]$SmokeTest = "tests/test_security_passwords.py",
    [string]$NodeExe = "",
    [switch]$RunAll
)

$ErrorActionPreference = "Stop"
$ProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))

function Resolve-NodeBinary {
    param(
        [string]$RequestedNodeExe,
        [string]$RootDir
    )

    if ($RequestedNodeExe) {
        $expanded = [Environment]::ExpandEnvironmentVariables($RequestedNodeExe)
        if (Test-Path $expanded) {
            return [System.IO.Path]::GetFullPath($expanded)
        }
        $fromPath = (Get-Command $RequestedNodeExe -ErrorAction SilentlyContinue)
        if ($fromPath) {
            return $fromPath.Source
        }
        throw "Configured Node executable not found: $RequestedNodeExe"
    }

    $globalNode = (Get-Command node -ErrorAction SilentlyContinue)
    if ($globalNode) {
        return $globalNode.Source
    }

    $localNodeDir = Join-Path $RootDir ".tools\node"
    $localNode = Get-ChildItem -Path $localNodeDir -Filter node.exe -Recurse -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($localNode) {
        return $localNode.FullName
    }

    return $null
}

function Install-LocalNodeLts {
    param([string]$RootDir)

    $nodeRoot = Join-Path $RootDir ".tools\node"
    New-Item -ItemType Directory -Path $nodeRoot -Force | Out-Null

    Write-Host "Node.js not found in PATH. Downloading latest LTS (win-x64)..."
    $releases = Invoke-RestMethod -Uri "https://nodejs.org/dist/index.json"
    $release = $releases |
        Where-Object { $_.lts -and $_.files -contains "win-x64-zip" } |
        Select-Object -First 1
    if (-not $release) {
        throw "Unable to find a Node.js LTS release with win-x64 zip package."
    }

    $version = $release.version
    $zipName = "node-$version-win-x64.zip"
    $zipUrl = "https://nodejs.org/dist/$version/$zipName"
    $zipPath = Join-Path $nodeRoot $zipName
    $extractDir = Join-Path $nodeRoot "node-$version-win-x64"

    Write-Host "Downloading Node.js $version from $zipUrl"
    Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath

    if (Test-Path $extractDir) {
        Remove-Item -LiteralPath $extractDir -Recurse -Force
    }
    Expand-Archive -Path $zipPath -DestinationPath $nodeRoot -Force
    Remove-Item -LiteralPath $zipPath -Force

    $nodeBinary = Join-Path $extractDir "node.exe"
    if (-not (Test-Path $nodeBinary)) {
        throw "Node.js downloaded but node.exe not found at $nodeBinary"
    }
    return $nodeBinary
}

Write-Host "Using Python interpreter: $PythonExe"
& $PythonExe --version

Write-Host "Recreating virtual environment (.venv)..."
& $PythonExe -m venv .venv --clear

$VenvPython = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
$VenvPython = [System.IO.Path]::GetFullPath($VenvPython)

Write-Host "Installing dependencies from requirements-dev.txt..."
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r (Join-Path $PSScriptRoot "..\requirements-dev.txt")

$resolvedNode = Resolve-NodeBinary -RequestedNodeExe $NodeExe -RootDir $ProjectRoot
if (-not $resolvedNode) {
    $resolvedNode = Install-LocalNodeLts -RootDir $ProjectRoot
}
$env:NODE_BINARY = $resolvedNode
Write-Host "Using Node executable: $resolvedNode"
& $resolvedNode --version

if ($RunAll) {
    Write-Host "Running full test suite..."
    & $VenvPython -m pytest -q
}
else {
    Write-Host "Running smoke test: $SmokeTest"
    & $VenvPython -m pytest -q $SmokeTest
}

Write-Host "Done."
