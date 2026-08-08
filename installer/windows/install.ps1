# installer/windows/install.ps1

$ErrorActionPreference = "Stop"

$Repository = "matrixd0t/commamatrix"
$Version = "0.1.4"
$Tag = "v$Version"
$BootstrapUrl = "https://raw.githubusercontent.com/$Repository/$Tag/installer/windows/bootstrap.py"
$BootstrapPath = Join-Path ([System.IO.Path]::GetTempPath()) "commamatrix-bootstrap-$Version.py"

function Refresh-UserPath {
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machinePath;$userPath"
}

function Find-Uv {
    Refresh-UserPath
    $command = Get-Command uv -ErrorAction SilentlyContinue
    if ($null -ne $command) {
        return $command.Source
    }
    return $null
}

try {
    $uv = Find-Uv
    if ($null -eq $uv) {
        $uvInstaller = Invoke-WebRequest -UseBasicParsing -Uri "https://astral.sh/uv/install.ps1"
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -Command $uvInstaller.Content *> $null
        $uv = Find-Uv
    }

    if ($null -eq $uv) {
        throw "uv was not found after installation"
    }

    Invoke-WebRequest -UseBasicParsing -Uri $BootstrapUrl -OutFile $BootstrapPath
    & $uv run --quiet --python 3.13 $BootstrapPath --repository $Repository --version $Version --uv $uv
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}
catch {
    Write-Error $_
    exit 1
}
finally {
    if (Test-Path -LiteralPath $BootstrapPath) {
        Remove-Item -LiteralPath $BootstrapPath -Force -ErrorAction SilentlyContinue
    }
}
