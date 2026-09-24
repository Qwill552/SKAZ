param(
    [string]$InstallDir,
    [switch]$Unattended,
    [switch]$DeleteData,
    [switch]$KeepLauncher,
    [ValidateSet('Models','SKAZ')][string]$Target = 'SKAZ'
)
. "$PSScriptRoot\common.ps1"
$Candidate = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..')).TrimEnd('\')
$Packaged = (Split-Path $Candidate -Leaf) -eq '_internal'
$CandidateFolder = if ($Packaged) { Split-Path $Candidate -Parent } else { $Candidate }
if (-not $InstallDir) {
    $Legacy = Join-Path $env:LOCALAPPDATA 'skaz'
    $InstallDir = if (Test-Path -LiteralPath (Join-Path $Candidate '.skaz-install.json')) { $Candidate }
                  elseif ($Packaged -and (Test-Path -LiteralPath (Join-Path $CandidateFolder '.skaz-install.json'))) { $CandidateFolder }
                  elseif (Test-Path -LiteralPath (Join-Path $Legacy '.skaz-install.json')) { $Legacy }
                  else { $Candidate }
}
$Root = Assert-SkazRoot $InstallDir
if ($Packaged -and $Root -ne $Candidate -and
    (Test-Path -LiteralPath (Join-Path $Root '_internal\.skaz-install.json'))) {
    $Root = Join-Path $Root '_internal'
}
$InstallFolder = if ($Packaged -and (Split-Path $Root -Leaf) -eq '_internal') { Split-Path $Root -Parent } else { $Root }
$Maintenance = $Instance = $null
try {
    if (-not $Unattended) {
        $Choice = Read-Host "Что удалить?`n1. Голосовые модели`n2. SKAZ`nВыберите 1 или 2"
        switch ($Choice) {
            '1' { $Target = 'Models' }
            '2' { $Target = 'SKAZ' }
            default { Write-Host 'Удаление отменено.'; return }
        }
    }
    $Marker = Join-Path $Root '.skaz-install.json'
    if (-not (Test-Path -LiteralPath $Marker)) { throw 'No completed SKAZ installation found here.' }
    if ((Get-Item -LiteralPath $Root -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw 'Installation directory is a link.'
    }
    $Metadata = Get-Content -LiteralPath $Marker -Encoding UTF8 -Raw | ConvertFrom-Json
    if ($Metadata.root -ne $Root) { throw 'Installation path does not match its marker.' }
    if (-not $Unattended) {
        $Question = if ($Target -eq 'Models') { "Удалить все голосовые модели из $InstallFolder ? [y/N]" }
                    else { "Удалить всю папку $InstallFolder вместе с SKAZ, моделями и остальными файлами? [y/N]" }
        if ((Read-Host $Question) -notmatch '^(y|д)$') { Write-Host 'Удаление отменено.'; return }
        if ($Target -eq 'SKAZ') {
            $DeleteData = (Read-Host 'Удалить также ключ и пользовательский словарь? [y/N]') -match '^(y|д)$'
        }
    }
    $Maintenance = Open-SkazLock (Join-Path $Root '.maintenance.lock')
    if ($Target -eq 'Models') {
        Write-Host '[1/2] Останавливаю SKAZ и освобождаю файлы моделей...'
        $Instance = Stop-Skaz $Root
        $Models = Join-Path $Root 'models'
        if (Test-Path -LiteralPath $Models) {
            Write-Host '[2/2] Удаляю голосовые модели...'
            Remove-SkazChild $Root $Models 'Голосовые модели'
            Write-Host 'Голосовые модели удалены. SKAZ скачает выбранную модель при следующем чтении.'
        } else {
            Write-Host '[2/2] Голосовые модели уже удалены.'
        }
        return
    }
    [IO.File]::WriteAllText((Join-Path $Root '.uninstalling'), 'SKAZ', $Utf8)
    Write-Host '[1/4] Останавливаю SKAZ и освобождаю файлы...'
    $Instance = Stop-Skaz $Root
    if (-not $DeleteData) {
        Write-Host '[2/4] Сохраняю ключ и пользовательский словарь...'
        $Backup = Join-Path (Split-Path $InstallFolder -Parent) ('skaz-backup-' + [DateTime]::Now.ToString('yyyyMMdd-HHmmss-fff'))
        New-Item -ItemType Directory -Path $Backup | Out-Null
        foreach ($Name in @('config.json','user_dict.json')) {
            $Path = Join-Path $Root $Name
            if (Test-Path -LiteralPath $Path) { Copy-Item -LiteralPath $Path -Destination $Backup }
        }
        Write-Host "Ключ и словарь сохранены: $Backup"
    } else {
        Write-Host '[2/4] Ключ и пользовательский словарь будут удалены.'
    }
    Write-Host '[3/4] Удаляю ярлыки и регистрацию skaz://...'
    & "$Root\packaging\shortcuts.ps1" -Root $Root -Action Remove
    $Protocol = 'HKCU:\Software\Classes\skaz'
    if (Test-Path -LiteralPath "$Protocol\shell\open\command") {
        $Command = (Get-Item -LiteralPath "$Protocol\shell\open\command").GetValue('')
        if ($Command -and $Command.Contains($Root + '\')) {
            Remove-Item -LiteralPath $Protocol -Recurse -Force
        }
    }
    $Instance.Dispose(); $Instance = $null
    $Maintenance.Dispose(); $Maintenance = $null
    Set-Location -LiteralPath (Split-Path $InstallFolder -Parent)
    $LauncherPending = $KeepLauncher -and ($CandidateFolder -eq $InstallFolder) -and
                       (Test-Path -LiteralPath (Join-Path $InstallFolder 'uninstall.bat'))
    $Children = @(Get-ChildItem -LiteralPath $InstallFolder -Force |
                  Where-Object { -not $LauncherPending -or $_.Name -ne 'uninstall.bat' })
    $Total = $Children.Count
    for ($Index = 0; $Index -lt $Total; $Index++) {
        $Child = $Children[$Index]
        Write-Host ("[4/4] Удаляю {0}/{1}: {2}" -f ($Index + 1), $Total, $Child.Name)
        Remove-SkazChild $InstallFolder $Child.FullName $Child.Name
    }
    if (-not $LauncherPending) { Remove-SkazChild (Split-Path $InstallFolder -Parent) $InstallFolder }
    Write-Host 'SKAZ удалён. Юзерскрипт удаляется отдельно в Tampermonkey.'
} catch {
    Write-Host "Ошибка удаления: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
} finally {
    if ($Instance) { $Instance.Dispose() }
    if ($Maintenance) { $Maintenance.Dispose() }
}
