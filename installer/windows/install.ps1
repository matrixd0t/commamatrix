# installer/windows/install.ps1

$ErrorActionPreference = "Stop"

$Repository = "matrixd0t/commamatrix"
$Branch = "master"
$PythonInstallerVersion = "3.13.15"
$PythonInstallerUrl = "https://www.python.org/ftp/python/$PythonInstallerVersion/python-$PythonInstallerVersion-amd64.exe"
$InstallRoot = Join-Path $HOME "commamatrix"
$PythonRuntimeRoot = Join-Path $HOME ".python"
$PythonRuntimePath = Join-Path $PythonRuntimeRoot "python.exe"
$VenvPath = Join-Path $InstallRoot ".venv"
$TempRoot = Join-Path ([System.IO.Path]::GetTempPath()) "commamatrix-installer-$PID"
$BootstrapPath = Join-Path $TempRoot "bootstrap.py"
$ProvidersPath = Join-Path $TempRoot "providers.json"
$TemplatePath = Join-Path $TempRoot "entrypoint.template.py"
$ResultPath = Join-Path $TempRoot "entrypoint-path.txt"
$LogoPngPath = Join-Path $TempRoot "logo.png"
$LogoIcoPath = Join-Path $TempRoot "logo.ico"

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

function Find-Python313 {
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($null -eq $launcher) {
        return $null
    }

    $candidate = & $launcher.Source @(
        "-3.13",
        "-c",
        "import sys; print(sys.executable)"
    ) 2>$null
    if ($LASTEXITCODE -ne 0) {
        return $null
    }

    $path = ($candidate | Out-String).Trim()
    if (-not [string]::IsNullOrWhiteSpace($path) -and (Test-Path -LiteralPath $path)) {
        return $path
    }
    return $null
}

function Get-Python313 {
    if (Test-Path -LiteralPath $PythonRuntimePath) {
        return $PythonRuntimePath
    }

    $systemPython = Find-Python313
    if ($null -ne $systemPython) {
        return $systemPython
    }

    $installerPath = Join-Path $TempRoot "python-$PythonInstallerVersion-amd64.exe"
    Write-Host "Downloading Python $PythonInstallerVersion..."
    Invoke-WebRequest -UseBasicParsing -Uri $PythonInstallerUrl -OutFile $installerPath
    New-Item -ItemType Directory -Path $PythonRuntimeRoot -Force | Out-Null
    Invoke-External -FilePath $installerPath -ArgumentList @(
        "/quiet",
        "InstallAllUsers=0",
        "PrependPath=0",
        "Include_launcher=0",
        "Include_test=0",
        "Include_pip=1",
        "TargetDir=$PythonRuntimeRoot"
    )
    if (-not (Test-Path -LiteralPath $PythonRuntimePath)) {
        throw "Python $PythonInstallerVersion was not installed: $PythonRuntimePath"
    }
    return $PythonRuntimePath
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

    $PythonPath = Get-Python313
    Invoke-External -FilePath $PythonPath -ArgumentList @(
        "-m",
        "venv",
        "--clear",
        "--copies",
        $VenvPath
    )

    $VenvPython = Join-Path $VenvPath "Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $VenvPython)) {
        throw "Python virtual environment was not created: $VenvPath"
    }

    Invoke-External -FilePath $VenvPython -ArgumentList @(
        "-m",
        "pip",
        "install",
        "--upgrade",
        "--index-url",
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

    $PythonwPath = Join-Path (Split-Path -Parent $PythonPath) "pythonw.exe"
    if (-not (Test-Path -LiteralPath $PythonwPath)) {
        throw "The original Python GUI binary was not found: $PythonwPath"
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
