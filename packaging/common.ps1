$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$Utf8 = New-Object System.Text.UTF8Encoding($false)

function Assert-SkazRoot([string]$Path) {
    $Full = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    if ($Full -eq [IO.Path]::GetPathRoot($Full).TrimEnd('\') -or
        $Full -eq [Environment]::GetFolderPath('UserProfile') -or
        $Full -eq [Environment]::GetFolderPath('LocalApplicationData')) {
        throw "Unsafe installation directory: $Full"
    }
    return $Full
}

function Remove-SkazChild([string]$Root, [string]$Path, [string]$ProgressLabel = '') {
    $Base = [IO.Path]::GetFullPath($Root).TrimEnd('\') + '\'
    $Full = Assert-SkazRoot $Path
    if (-not $Full.StartsWith($Base, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Path is outside installation: $Full"
    }
    if (Test-Path -LiteralPath $Full) {
        # uv creates a version-alias junction in python/. Remove links themselves
        # without traversing them; then recursive deletion cannot leave the root.
        $Pending = New-Object 'Collections.Generic.Stack[string]'
        $Pending.Push($Full)
        $Checked = 0
        while ($Pending.Count) {
            $Current = Get-Item -LiteralPath $Pending.Pop() -Force
            if ($ProgressLabel) {
                $Checked++
                if ($Checked % 1000 -eq 0) {
                    Write-Host ("  {0}: проверено {1} объектов" -f $ProgressLabel, $Checked)
                }
            }
            if ($Current.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                if ($Current.PSIsContainer) { [IO.Directory]::Delete($Current.FullName) }
                else { Remove-Item -LiteralPath $Current.FullName -Force }
            } elseif ($Current.PSIsContainer) {
                foreach ($Child in Get-ChildItem -LiteralPath $Current.FullName -Force) {
                    $Pending.Push($Child.FullName)
                }
            }
        }
        if ($ProgressLabel -and $Checked -ge 1000) {
            Write-Host ("  {0}: удаляю {1} объектов" -f $ProgressLabel, $Checked)
        }
        if (Test-Path -LiteralPath $Full) { Remove-Item -LiteralPath $Full -Recurse -Force }
    }
}

function Open-SkazLock([string]$Path) {
    return [IO.File]::Open($Path, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
}

function Stop-Skaz([string]$Root) {
    # A stopped or interrupted installation may have incomplete Python code.
    # If no controller owns the lock, do not import that code merely to stop it.
    try { return Open-SkazLock (Join-Path $Root '.instance.lock') }
    catch [IO.IOException] { }
    $Python = Join-Path $Root '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $Python) {
        Push-Location -LiteralPath $Root
        try {
            & $Python -m server.tray quit | Out-Null
            if ($LASTEXITCODE -ne 0) { throw 'SKAZ did not acknowledge shutdown. See logs\skaz.log.' }
        } finally { Pop-Location }
    }
    $Deadline = [DateTime]::UtcNow.AddSeconds(15)
    do {
        try { return Open-SkazLock (Join-Path $Root '.instance.lock') }
        catch [IO.IOException] { Start-Sleep -Milliseconds 100 }
    } while ([DateTime]::UtcNow -lt $Deadline)
    throw 'SKAZ is still running. Files have not been replaced.'
}

function Invoke-Uv([string[]]$UvArgs) {
    & $script:Uv @UvArgs
    if ($LASTEXITCODE -ne 0) { throw "uv failed ($LASTEXITCODE): $($UvArgs -join ' ')" }
}
