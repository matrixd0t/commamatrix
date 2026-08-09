# installer/windows/install.ps1

$ErrorActionPreference = "Stop"

$Repository = "matrixd0t/commamatrix"
$Branch = "master"
$InstallRoot = Join-Path $HOME "commamatrix"
$VenvPath = Join-Path $InstallRoot ".venv"
$TempRoot = Join-Path ([System.IO.Path]::GetTempPath()) "commamatrix-installer-$PID"
$BootstrapPath = Join-Path $TempRoot "bootstrap.py"
$ProvidersPath = Join-Path $TempRoot "providers.json"
$TemplatePath = Join-Path $TempRoot "entrypoint.template.py"
$ResultPath = Join-Path $TempRoot "entrypoint-path.txt"
$LogoPngPath = Join-Path $TempRoot "logo.png"
$LogoIcoPath = Join-Path $TempRoot "logo.ico"
$UvInstallerPath = Join-Path $TempRoot "uv-install.ps1"

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

function Invoke-External {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [Parameter(Mandatory = $true)]
        [string[]]$ArgumentList
    )

    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "$FilePath exited with code $LASTEXITCODE"
    }
}

function DownloadInstallerResource {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [string]$Destination
    )

    if (-not [string]::IsNullOrWhiteSpace($PSScriptRoot)) {
        $localPath = Join-Path $PSScriptRoot $Name
        if (Test-Path -LiteralPath $localPath) {
            Copy-Item -LiteralPath $localPath -Destination $Destination -Force
            return
        }
    }

    $url = "https://raw.githubusercontent.com/$Repository/$Branch/installer/windows/$Name"
    Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $Destination
}

function DownloadAsset {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [string]$Destination
    )

    if (-not [string]::IsNullOrWhiteSpace($PSScriptRoot)) {
        $repositoryRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
        $localPath = Join-Path $repositoryRoot ("assets\" + $Name)
        if (Test-Path -LiteralPath $localPath) {
            Copy-Item -LiteralPath $localPath -Destination $Destination -Force
            return
        }
    }

    $url = "https://raw.githubusercontent.com/$Repository/$Branch/assets/$Name"
    Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $Destination
}

function New-DesktopShortcut {
    param(
        [Parameter(Mandatory = $true)]
        [string]$TargetPath,
        [Parameter(Mandatory = $true)]
        [string]$EntrypointPath,
        [Parameter(Mandatory = $true)]
        [string]$WorkingDirectory,
        [Parameter(Mandatory = $true)]
        [string]$IconPath
    )

    $desktopPath = [Environment]::GetFolderPath("Desktop")
    if ([string]::IsNullOrWhiteSpace($desktopPath)) {
        $desktopPath = Join-Path $HOME "Desktop"
    }
    New-Item -ItemType Directory -Path $desktopPath -Force | Out-Null

    $shortcutPath = Join-Path $desktopPath "CommaMatrix.lnk"
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $TargetPath
    $shortcut.Arguments = '"' + $EntrypointPath + '"'
    $shortcut.WorkingDirectory = $WorkingDirectory
    $shortcut.IconLocation = "$IconPath,0"
    $shortcut.Save()
    Write-Host "Desktop shortcut created: $shortcutPath"
}

try {
    New-Item -ItemType Directory -Path $InstallRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $TempRoot -Force | Out-Null

    $uv = Find-Uv
    if ($null -eq $uv) {
        Invoke-WebRequest -UseBasicParsing -Uri "https://astral.sh/uv/install.ps1" -OutFile $UvInstallerPath
        Invoke-External -FilePath "powershell.exe" -ArgumentList @(
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            $UvInstallerPath
        )
        $uv = Find-Uv
    }

    if ($null -eq $uv) {
        throw "uv was not found after installation"
    }

    Invoke-External -FilePath $uv -ArgumentList @(
        "python",
        "install",
        "3.13"
    )
    Invoke-External -FilePath $uv -ArgumentList @(
        "venv",
        "--python",
        "3.13",
        "--managed-python",
        "--clear",
        "--no-project",
        $VenvPath
    )

    $VenvPython = Join-Path $VenvPath "Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $VenvPython)) {
        throw "Python virtual environment was not created: $VenvPath"
    }

    Invoke-External -FilePath $uv -ArgumentList @(
        "pip",
        "install",
        "--python",
        $VenvPython,
        "--upgrade",
        "--default-index",
        "https://pypi.org/simple",
        "commamatrix[all]",
        "Pillow",
        "pystray"
    )

    DownloadInstallerResource -Name "bootstrap.py" -Destination $BootstrapPath
    DownloadInstallerResource -Name "providers.json" -Destination $ProvidersPath
    DownloadInstallerResource -Name "entrypoint.template.py" -Destination $TemplatePath
    DownloadAsset -Name "logo.png" -Destination $LogoPngPath
    DownloadAsset -Name "logo.ico" -Destination $LogoIcoPath

    Invoke-External -FilePath $VenvPython -ArgumentList @(
        $BootstrapPath,
        "--providers",
        $ProvidersPath,
        "--template",
        $TemplatePath,
        "--venv",
        $VenvPath,
        "--result-file",
        $ResultPath
    )

    $EntrypointPath = (Get-Content -LiteralPath $ResultPath -Raw -Encoding UTF8).Trim()
    if ([string]::IsNullOrWhiteSpace($EntrypointPath) -or -not (Test-Path -LiteralPath $EntrypointPath)) {
        throw "Bootstrap did not produce an entrypoint"
    }

    $PythonwPath = Join-Path $VenvPath "Scripts\pythonw.exe"
    if (-not (Test-Path -LiteralPath $PythonwPath)) {
        throw "pythonw.exe was not created in the virtual environment: $VenvPath"
    }

    $WorkspacePath = Split-Path -Parent $EntrypointPath
    $AssetsPath = Join-Path $WorkspacePath ".commamatrix\assets"
    New-Item -ItemType Directory -Path $AssetsPath -Force | Out-Null
    $PersistentLogoPng = Join-Path $AssetsPath "logo.png"
    $PersistentLogoIco = Join-Path $AssetsPath "logo.ico"
    Copy-Item -LiteralPath $LogoPngPath -Destination $PersistentLogoPng -Force
    Copy-Item -LiteralPath $LogoIcoPath -Destination $PersistentLogoIco -Force

    New-DesktopShortcut `
        -TargetPath $PythonwPath `
        -EntrypointPath $EntrypointPath `
        -WorkingDirectory $WorkspacePath `
        -IconPath $PersistentLogoIco
}
catch {
    Write-Error $_
    exit 1
}
finally {
    if (Test-Path -LiteralPath $TempRoot) {
        Remove-Item -LiteralPath $TempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
    Write-Host ""
    Read-Host "Press Enter to exit"
}
