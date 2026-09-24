param(
    [string]$InstallDir,
    [string]$UvPath,
    [string]$Model,
    [switch]$Autostart,
    [switch]$Unattended,
    [switch]$NoLaunch
)
. "$PSScriptRoot\common.ps1"
$Source = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..')).TrimEnd('\')
$Packaged = (Split-Path $Source -Leaf) -eq '_internal'
$SourceFolder = if ($Packaged) { Split-Path $Source -Parent } else { $Source }
if (-not $InstallDir) {
    $InstallDir = $SourceFolder
}
$InstallFolder = Assert-SkazRoot $InstallDir
$Root = if ($Packaged) { Join-Path $InstallFolder '_internal' } else { $InstallFolder }
$Maintenance = $Instance = $null
$LegacyInstance = $null
$LegacyMaintenance = $null
$ConsoleModeSaved = $false

function Disable-InstallerQuickEdit {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class SkazInstallerConsole {
    [DllImport("kernel32.dll")] public static extern IntPtr GetStdHandle(int id);
    [DllImport("kernel32.dll")] public static extern bool GetConsoleMode(IntPtr handle, out uint mode);
    [DllImport("kernel32.dll")] public static extern bool SetConsoleMode(IntPtr handle, uint mode);
}
'@
    $script:ConsoleInput = [SkazInstallerConsole]::GetStdHandle(-10)
    $script:OriginalConsoleMode = [uint32]0
    if ([SkazInstallerConsole]::GetConsoleMode($script:ConsoleInput, [ref]$script:OriginalConsoleMode)) {
        $Mode = ($script:OriginalConsoleMode -bor 0x80) -band (-bnot 0x40)
        $script:ConsoleModeSaved = [SkazInstallerConsole]::SetConsoleMode($script:ConsoleInput, $Mode)
    }
}

function Get-Uv {
    $Bin = Join-Path $Root 'bin'
    New-Item -ItemType Directory -Path $Bin -Force | Out-Null
    $script:Uv = Join-Path $Bin 'uv.exe'
    if (Test-Path -LiteralPath $script:Uv) { return }
    if ($UvPath) {
        Copy-Item -LiteralPath $UvPath -Destination $script:Uv
        return
    }
    $Version = '0.12.17'
    $Asset = 'uv-x86_64-pc-windows-msvc.zip'
    $Url = "https://github.com/astral-sh/uv/releases/download/$Version/$Asset"
    $Zip = Join-Path $Bin $Asset
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Zip
    $ChecksumPath = "$Zip.sha256"
    Invoke-WebRequest -UseBasicParsing -Uri "$Url.sha256" -OutFile $ChecksumPath
    # GitHub serves this asset as octet-stream: .Content may be byte[], not text.
    $Expected = ([IO.File]::ReadAllText($ChecksumPath)).Trim().Split(' ')[0]
    if ($Expected -notmatch '^[0-9a-fA-F]{64}$' -or
        (Get-FileHash -LiteralPath $Zip -Algorithm SHA256).Hash -ne $Expected) {
        throw 'uv archive checksum mismatch. Restart the installer.'
    }
    Expand-Archive -LiteralPath $Zip -DestinationPath $Bin -Force
    Remove-Item -LiteralPath $Zip
    Remove-Item -LiteralPath $ChecksumPath
    if (-not (Test-Path -LiteralPath $script:Uv)) { throw 'uv.exe missing from archive.' }
}

function Choose-Autostart {
    Write-Host 'Модель загружается при чтении и освобождает память через 10 минут простоя.'
    $Answer = Read-Host 'Запускать SKAZ при входе в Windows? [y/д/N]'
    return ($Answer -match '^(y|yes|д|да)$')
}

try {
    Disable-InstallerQuickEdit
    if (-not [Environment]::Is64BitOperatingSystem) { throw 'SKAZ requires 64-bit Windows.' }
    Write-Host "SKAZ: $InstallFolder"
    Write-Host 'Python 3.12, CPU torch, Silero. Около 0.8-1.2 ГБ; нужно 2 ГБ свободного места.'
    Write-Host 'Windows может показать предупреждение о неподписанном файле. Защиту отключать не нужно.'
    $ExistingCurrent = Test-Path -LiteralPath (Join-Path $Root '.skaz-install.json')
    $ExistingLegacy = $Packaged -and (Test-Path -LiteralPath (Join-Path $InstallFolder '.skaz-install.json'))
    $Existing = $ExistingCurrent -or $ExistingLegacy
    $LegacyRoot = Join-Path $env:LOCALAPPDATA 'skaz'
    if (-not $Existing -and $Root -eq $Source -and $LegacyRoot -ne $InstallFolder -and
        (Test-Path -LiteralPath (Join-Path $LegacyRoot '.skaz-install.json'))) {
        throw "Найдена прежняя установка: $LegacyRoot. Удалите её через uninstall.bat, затем повторите установку в $InstallFolder."
    }
    if ((Test-Path -LiteralPath $InstallFolder) -and
        ((Get-Item -LiteralPath $InstallFolder -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'Installation directory is a link.'
    }
    if ((Test-Path -LiteralPath $Root) -and
        ((Get-Item -LiteralPath $Root -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'Application directory is a link.'
    }
    if ((Test-Path -LiteralPath $InstallFolder) -and -not $Existing -and
        @(Get-ChildItem -LiteralPath $InstallFolder -Force).Count -gt 0 -and
        -not (Test-Path -LiteralPath (Join-Path $Root '.installing')) -and $Source -ne $Root) {
        throw 'Destination is not an SKAZ installation. Choose an empty directory.'
    }
    if (-not $Unattended) {
        if ($Existing) {
            if ((Read-Host 'SKAZ уже установлен. Обновить? [y/N]') -notmatch '^(y|д)$') { return }
        } else { [void](Read-Host "Нажмите Enter для установки в $InstallFolder (Ctrl+C — выход). При удалении вся эта папка будет удалена") }
    }
    New-Item -ItemType Directory -Path $Root -Force | Out-Null
    $Maintenance = Open-SkazLock (Join-Path $Root '.maintenance.lock')
    [IO.File]::WriteAllText((Join-Path $Root '.installing'), 'SKAZ', $Utf8)
    $Instance = Stop-Skaz $Root
    $WasAutostart = $false
    if ($ExistingLegacy) {
        $LegacyMetadata = Get-Content -LiteralPath (Join-Path $InstallFolder '.skaz-install.json') -Encoding UTF8 -Raw | ConvertFrom-Json
        if ($LegacyMetadata.root -ne $InstallFolder) { throw 'Previous installation path does not match its marker.' }
        $LegacyMaintenance = Open-SkazLock (Join-Path $InstallFolder '.maintenance.lock')
        $LegacyInstance = Stop-Skaz $InstallFolder
        $WasAutostart = & (Join-Path $InstallFolder 'packaging\shortcuts.ps1') -Root $InstallFolder -Action Status
        & (Join-Path $InstallFolder 'packaging\shortcuts.ps1') -Root $InstallFolder -Action Remove
        foreach ($Name in @('config.json','user_dict.json','models','logs')) {
            $OldPath = Join-Path $InstallFolder $Name
            $NewPath = Join-Path $Root $Name
            if (Test-Path -LiteralPath $OldPath) {
                if (Test-Path -LiteralPath $NewPath) { throw "Обнаружены две копии $Name; разберите их вручную." }
                Move-Item -LiteralPath $OldPath -Destination $NewPath
            }
        }
        $LegacyInstance.Dispose(); $LegacyInstance = $null
        $LegacyMaintenance.Dispose(); $LegacyMaintenance = $null
    }
    Write-Host '[1/6] Подготовка файлов приложения'
    $Files = @('run.bat','run.vbs','handler.vbs','autostart.bat',
               'pyproject.toml','uv.lock','.python-version','models.json','skaz.svg')
    if (-not $Packaged) { $Files += @('install.bat','uninstall.bat','README.txt') }
    if ($Source -ne $Root) {
        foreach ($Name in $Files) { Copy-Item -LiteralPath (Join-Path $Source $Name) -Destination $Root -Force }
        foreach ($Name in @('server','packaging')) {
            Remove-SkazChild $Root (Join-Path $Root $Name)
            Copy-Item -LiteralPath (Join-Path $Source $Name) -Destination $Root -Recurse
        }
        if ($Packaged) {
            foreach ($Name in @('install.bat','uninstall.bat','README.txt')) {
                Copy-Item -LiteralPath (Join-Path $SourceFolder $Name) -Destination $InstallFolder -Force
            }
            New-Item -ItemType Directory -Path (Join-Path $InstallFolder 'userscript') -Force | Out-Null
            Copy-Item -LiteralPath (Join-Path $SourceFolder 'userscript\skaz.user.js') -Destination (Join-Path $InstallFolder 'userscript') -Force
        } else {
            Copy-Item -LiteralPath (Join-Path $Source 'userscript') -Destination $Root -Recurse -Force
        }
    }
    Write-Host '[2/6] uv и Python 3.12'
    Get-Uv
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $Root 'python'
    $env:UV_PYTHON_BIN_DIR = Join-Path $Root 'bin'
    $env:UV_CACHE_DIR = Join-Path $Root '.uv-cache'
    $env:UV_PYTHON_PREFERENCE = 'only-managed'
    $env:UV_LINK_MODE = 'copy'
    $env:UV_PROJECT_ENVIRONMENT = Join-Path $Root '.venv'
    Push-Location -LiteralPath $Root
    try {
        Invoke-Uv @('python','install','3.12','--no-bin')
        Write-Host '[3/6] Зависимости (версии из uv.lock)'
        Invoke-Uv @('sync','--locked','--no-dev','--no-editable','--python','3.12')
        $Python = Join-Path $Root '.venv\Scripts\python.exe'
        Write-Host '[4/6] Модель, SHA-256 и конфигурация'
        $PrepareArgs = @('-m','server.install_model')
        if ($Model) { $PrepareArgs += @('--model', $Model) }
        if ($Unattended) { $PrepareArgs += '--unattended' }
        & $Python @PrepareArgs
        if ($LASTEXITCODE -ne 0) { throw 'Model/configuration setup failed. Restart install.bat to retry.' }
        & $Python -c 'import torch; assert torch.version.cuda is None, "CUDA wheel is not supported"'
        if ($LASTEXITCODE -ne 0) { throw 'CPU torch verification failed.' }
    } finally { Pop-Location }
    Write-Host '[5/6] Ярлыки'
    & "$Root\packaging\shortcuts.ps1" -Root $Root -Action Install
    if ($ExistingLegacy -and $WasAutostart) {
        & "$Root\packaging\shortcuts.ps1" -Root $Root -Action Enable
    }
    $Protocol = 'HKCU:\Software\Classes\skaz'
    New-Item -Path "$Protocol\shell\open\command" -Force | Out-Null
    Set-Item -LiteralPath $Protocol -Value 'URL:SKAZ Protocol'
    New-ItemProperty -LiteralPath $Protocol -Name 'URL Protocol' -Value '' -PropertyType String -Force | Out-Null
    $ProtocolCommand = '"' + (Join-Path $env:SystemRoot 'System32\wscript.exe') + '" //nologo "' + (Join-Path $Root 'handler.vbs') + '" "%1"'
    Set-Item -LiteralPath "$Protocol\shell\open\command" -Value $ProtocolCommand
    if (-not $Existing) {
        $Enable = if ($Unattended) { [bool]$Autostart } else { Choose-Autostart }
        if ($Enable) { & "$Root\packaging\shortcuts.ps1" -Root $Root -Action Enable }
        Write-Host $(if ($Enable) { 'Автозапуск включён.' } else { 'Автозапуск выключен.' })
    }
    [IO.File]::WriteAllText((Join-Path $Root '.skaz-install.json'),
        (@{root=$Root; version=2; userscript_source=(Join-Path $InstallFolder 'userscript\skaz.user.js')} | ConvertTo-Json), $Utf8)
    Write-Host 'Очистка временного кэша установки — это может занять некоторое время…'
    Remove-SkazChild $Root (Join-Path $Root '.uv-cache')
    Remove-Item -LiteralPath (Join-Path $Root '.installing')
    if (Test-Path -LiteralPath (Join-Path $Root '.uninstalling')) {
        Remove-Item -LiteralPath (Join-Path $Root '.uninstalling')
    }
    if ($Packaged) {
        foreach ($Name in @('.skaz-install.json','.venv','bin','python','.uv-cache','.runtime','server','packaging',
                            'run.bat','run.vbs','handler.vbs','autostart.bat','pyproject.toml',
                            'uv.lock','.python-version','models.json','skaz.svg',
                            '.installing','.uninstalling','.instance.lock','.maintenance.lock')) {
            Remove-SkazChild $InstallFolder (Join-Path $InstallFolder $Name)
        }
        Remove-SkazChild $InstallFolder (Join-Path $InstallFolder 'userscript\tests')
    }
    $Bytes = (Get-ChildItem -LiteralPath $Root -File -Recurse -Force | Measure-Object Length -Sum).Sum
    Write-Host ('Размер установки: {0:N0} МБ' -f ($Bytes / 1MB))
    $Instance.Dispose(); $Instance = $null
    $Maintenance.Dispose(); $Maintenance = $null
    Write-Host '[6/6] Запуск SKAZ'
    if (-not $NoLaunch) {
        Start-Process -FilePath (Join-Path $env:SystemRoot 'System32\wscript.exe') -WindowStyle Hidden `
            -ArgumentList ('//nologo "' + (Join-Path $Root 'run.vbs') + '" setup')
    }
    Write-Host 'Готово. Управление сервером — через значок SKAZ в трее.'
} catch {
    Write-Host "Ошибка: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host 'Повторите install.bat после устранения причины. Ключ, словарь и модели сохраняются.'
    exit 1
} finally {
    if ($Instance) { $Instance.Dispose() }
    if ($LegacyInstance) { $LegacyInstance.Dispose() }
    if ($LegacyMaintenance) { $LegacyMaintenance.Dispose() }
    if ($Maintenance) { $Maintenance.Dispose() }
    if ($ConsoleModeSaved) {
        [void][SkazInstallerConsole]::SetConsoleMode($ConsoleInput, $OriginalConsoleMode)
    }
}
