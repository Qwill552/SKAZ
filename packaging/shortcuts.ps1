param(
    [Parameter(Mandatory=$true)][string]$Root,
    [ValidateSet('Install','Enable','Disable','Remove','Status','Toggle')][string]$Action = 'Status'
)
. "$PSScriptRoot\common.ps1"
$Root = Assert-SkazRoot $Root
$Shell = New-Object -ComObject WScript.Shell
$Startup = Join-Path ([Environment]::GetFolderPath('Startup')) 'SKAZ.lnk'
$StartMenu = Join-Path ([Environment]::GetFolderPath('Programs')) 'SKAZ.lnk'
$Arguments = '//nologo "' + (Join-Path $Root 'run.vbs') + '"'

function Test-OwnedShortcut([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $false }
    return $Shell.CreateShortcut($Path).Arguments -eq $Arguments
}

function Save-Shortcut([string]$Path) {
    if ((Test-Path -LiteralPath $Path) -and -not (Test-OwnedShortcut $Path)) {
        throw "Another SKAZ installation owns this shortcut: $Path"
    }
    $Link = $Shell.CreateShortcut($Path)
    $Link.TargetPath = Join-Path $env:SystemRoot 'System32\wscript.exe'
    $Link.Arguments = $Arguments
    $Link.WorkingDirectory = $Root
    $Link.IconLocation = (Join-Path $Root 'packaging\skaz.ico') + ',0'
    $Link.Description = 'SKAZ - локальное чтение текста'
    $Link.Save()
}

switch ($Action) {
    'Toggle' {
        if (Test-OwnedShortcut $Startup) { Remove-Item -LiteralPath $Startup; Write-Host 'Автозапуск выключен' }
        else { Save-Shortcut $Startup; Write-Host 'Автозапуск включён' }
    }
    'Install' { Save-Shortcut $StartMenu }
    'Enable' { Save-Shortcut $Startup }
    'Disable' { if (Test-OwnedShortcut $Startup) { Remove-Item -LiteralPath $Startup } }
    'Remove' {
        foreach ($Path in @($Startup, $StartMenu)) {
            if (Test-OwnedShortcut $Path) { Remove-Item -LiteralPath $Path }
        }
    }
    'Status' { Test-OwnedShortcut $Startup }
}
