# installer/windows/install.ps1

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$Utf8Encoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = $Utf8Encoding
[Console]::OutputEncoding = $Utf8Encoding
[Console]::InputEncoding = $Utf8Encoding

function ConvertFrom-CodePoints {
    param(
        [Parameter(Mandatory = $true)]
        [string]$CodePoints
    )

    return -join ($CodePoints.Split(" ") | ForEach-Object { [char][Convert]::ToInt32($_, 16) })
}

$InstallingLibraries = ConvertFrom-CodePoints "0423 0441 0442 0430 043D 043E 0432 043A 0430 0020 0431 0438 0431 043B 0438 043E 0442 0435 043A 0438 002E 002E 002E"
$AdminPasswordLabel = ConvertFrom-CodePoints "041F 0430 0440 043E 043B 044C 0020 0430 0434 043C 0438 043D 0438 0441 0442 0440 0430 0442 043E 0440 0430"
$SavePasswordLabel = ConvertFrom-CodePoints "0421 043E 0445 0440 0430 043D 0438 0442 0435 0020 044D 0442 043E 0442 0020 043F 0430 0440 043E 043B 044C"
$ShortcutLabel = ConvertFrom-CodePoints "041A 043D 043E 043F 043A 0430 0020 0437 0430 043F 0443 0441 043A 0430 0020 0434 043E 0431 0430 0432 043B 0435 043D 0430 0020 043D 0430 0020 0440 0430 0431 043E 0447 0438 0439 0020 0441 0442 043E 043B"

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
$CredentialsPath = Join-Path $TempRoot "admin-credentials.json"
$LogoPngPath = Join-Path $TempRoot "logo.png"
$LogoIcoPath = Join-Path $TempRoot "logo.ico"

function Invoke-External {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [Parameter(Mandatory = $true)]
        [string[]]$ArgumentList,
        [switch]$Quiet
    )

    if ($Quiet) {
        & $FilePath @ArgumentList *> $null
    }
    else {
        & $FilePath @ArgumentList
    }
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
    Invoke-WebRequest -UseBasicParsing -Uri $PythonInstallerUrl -OutFile $installerPath
    New-Item -ItemType Directory -Path $PythonRuntimeRoot -Force | Out-Null
    Invoke-External -FilePath $installerPath -Quiet -ArgumentList @(
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
}

try {
    New-Item -ItemType Directory -Path $InstallRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $TempRoot -Force | Out-Null

    Write-Host "$InstallingLibraries / Installing libraries..."
    $PythonPath = Get-Python313
    Invoke-External -FilePath $PythonPath -Quiet -ArgumentList @(
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

    Invoke-External -FilePath $VenvPython -Quiet -ArgumentList @(
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

    Invoke-External -FilePath $VenvPython -ArgumentList @(
        $EntrypointPath,
        "--initialize",
        "--credentials-file",
        $CredentialsPath
    )
    if (-not (Test-Path -LiteralPath $CredentialsPath)) {
        throw "Entrypoint did not produce initial administrator credentials"
    }
    try {
        $AdminCredentials = Get-Content -LiteralPath $CredentialsPath -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    catch {
        throw "Could not read initial administrator credentials: $($_.Exception.Message)"
    }
    $AdminPassword = [string]$AdminCredentials.password
    if ([string]::IsNullOrWhiteSpace($AdminPassword)) {
        throw "Initial administrator credentials do not contain a password"
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

    Write-Host ""
    Write-Host "========================================"
    Write-Host "$AdminPasswordLabel / Administrator password:"
    Write-Host $AdminPassword
    Write-Host "$SavePasswordLabel / Save this password."
    Write-Host "========================================"
}
catch {
    Write-Error $_
    exit 1
}
finally {
    if (Test-Path -LiteralPath $TempRoot) {
        Remove-Item -LiteralPath $TempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
    Write-Host "$ShortcutLabel / Launch shortcut was added to desktop"
    Read-Host "Press Enter to exit"
}
