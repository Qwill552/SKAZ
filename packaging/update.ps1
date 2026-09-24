param([Parameter(Mandatory=$true)][string]$InstallDir)

$ErrorActionPreference = 'Stop'
$Repository = 'Qwill552/SKAZ'
$Asset = 'skaz-windows.zip'
$Log = Join-Path $InstallDir '_internal\logs\update.log'
$Work = Join-Path ([IO.Path]::GetTempPath()) ('skaz-update-' + [guid]::NewGuid().ToString('N'))

try {
    New-Item -ItemType Directory -Path $Work -Force | Out-Null
    $Base = "https://github.com/$Repository/releases/latest/download"
    $ManifestPath = Join-Path $Work 'version.json'
    Invoke-WebRequest -UseBasicParsing -Uri "$Base/version.json" -OutFile $ManifestPath
    $Manifest = Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($Manifest.version -notmatch '^\d+\.\d+\.\d+$') { throw 'Invalid release version' }
    Push-Location -LiteralPath (Join-Path $InstallDir '_internal')
    try {
        $InstalledVersion = & (Join-Path $InstallDir '_internal\.venv\Scripts\python.exe') -c 'from server.version import VERSION; print(VERSION)'
    } finally { Pop-Location }
    if ([version]$Manifest.version -le [version]$InstalledVersion.Trim()) { exit 0 }
    $Expected = $Manifest.assets.$Asset
    if ($Expected -notmatch '^[a-fA-F0-9]{64}$') { throw 'Invalid release checksum' }
    $ArchivePath = Join-Path $Work $Asset
    Invoke-WebRequest -UseBasicParsing -Uri "$Base/$Asset" -OutFile $ArchivePath
    $Actual = (Get-FileHash -LiteralPath $ArchivePath -Algorithm SHA256).Hash
    if ($Actual -ne $Expected) { throw 'Release checksum mismatch' }
    $Extracted = Join-Path $Work 'archive'
    Expand-Archive -LiteralPath $ArchivePath -DestinationPath $Extracted
    $Installer = Join-Path $Extracted '_internal\packaging\install.ps1'
    if (-not (Test-Path -LiteralPath $Installer)) { throw 'Installer missing from release' }
    & $Installer -InstallDir $InstallDir -Unattended
    if ($LASTEXITCODE -ne 0) { throw "Installer failed: $LASTEXITCODE" }
    Add-Content -LiteralPath $Log -Value "Updated to $($Manifest.version)" -Encoding UTF8
} catch {
    New-Item -ItemType Directory -Path (Split-Path $Log -Parent) -Force | Out-Null
    Add-Content -LiteralPath $Log -Value "Update failed: $($_.Exception.Message)" -Encoding UTF8
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show("Не удалось обновить SKAZ. Откройте журнал: $Log", 'SKAZ') | Out-Null
    exit 1
} finally {
    if (Test-Path -LiteralPath $Work) { Remove-Item -LiteralPath $Work -Recurse -Force }
    Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
}
