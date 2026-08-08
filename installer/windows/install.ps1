# installer/windows/install.ps1

$ErrorActionPreference = "Stop"

$Repository = "matrixd0t/commamatrix"
$Version = "0.1.11"
$Tag = "v$Version"
$BootstrapUrl = "https://raw.githubusercontent.com/$Repository/$Tag/installer/windows/bootstrap.py"
$BootstrapPath = Join-Path ([System.IO.Path]::GetTempPath()) "commamatrix-bootstrap-$Version.py"
$UvInstallerPath = Join-Path ([System.IO.Path]::GetTempPath()) "commamatrix-uv-installer-$Version.ps1"

function RefreshUserPath {
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machinePath;$userPath"
}

function Find-Uv {
    RefreshUserPath
    $command = Get-Command uv -ErrorAction SilentlyContinue
    if ($null -ne $command) {
        return $command.Source
    }
    return $null
}

try {
    $exitCode = 0
    $uv = Find-Uv
    if ($null -eq $uv) {
        Invoke-WebRequest -UseBasicParsing -Uri "https://astral.sh/uv/install.ps1" -OutFile $UvInstallerPath
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $UvInstallerPath
        if ($LASTEXITCODE -ne 0) {
            throw "uv installer exited with code $LASTEXITCODE"
        }
        $uv = Find-Uv
    }

    if ($null -eq $uv) {
        throw "uv was not found after installation"
    }

    Invoke-WebRequest -UseBasicParsing -Uri $BootstrapUrl -OutFile $BootstrapPath
    & $uv run --quiet --python 3.13 $BootstrapPath --repository $Repository --version $Version --uv $uv
    if ($LASTEXITCODE -ne 0) {
        $exitCode = $LASTEXITCODE
    }
}
catch {
    Write-Error $_
    $exitCode = 1
}
finally {
    if (Test-Path -LiteralPath $UvInstallerPath) {
        Remove-Item -LiteralPath $UvInstallerPath -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path -LiteralPath $BootstrapPath) {
        Remove-Item -LiteralPath $BootstrapPath -Force -ErrorAction SilentlyContinue
    }
    Write-Host ""
    Read-Host "Press Enter to exit"
}

exit $exitCode
