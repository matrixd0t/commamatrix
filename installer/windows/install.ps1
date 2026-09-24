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

$InstallingLibraries = ConvertFrom-CodePoints "0423 0441 0442 0430 043D 043E 0432 043A 0430 0020 0431 0438 0431 043B 0438 043E 0442 0435 043A 002E 002E 002E"
$AdminUsernameLabel = ConvertFrom-CodePoints "0418 043C 044F 0020 043F 043E 043B 044C 0437 043E 0432 0430 0442 0435 043B 044F"
$AdminPasswordLabel = ConvertFrom-CodePoints "041F 0430 0440 043E 043B 044C 0020 0430 0434 043C 0438 043D 0438 0441 0442 0440 0430 0442 043E 0440 0430"
$SavePasswordLabel = ConvertFrom-CodePoints "0421 043E 0445 0440 0430 043D 0438 0442 0435 0020 044D 0442 043E 0442 0020 043F 0430 0440 043E 043B 044C"
$ChangeCredentialsLabel = ConvertFrom-CodePoints "0412 044B 0020 0441 043C 043E 0436 0435 0442 0435 0020 0438 0437 043C 0435 043D 0438 0442 044C 0020 0438 043C 044F 0020 0438 0020 043F 0430 0440 043E 043B 044C 0020 0447 0435 0440 0435 0437 0020 0432 0435 0431 002D 0438 043D 0442 0435 0440 0444 0435 0439 0441"
$ShortcutLabel = ConvertFrom-CodePoints "041A 043D 043E 043F 043A 0430 0020 0437 0430 043F 0443 0441 043A 0430 0020 0434 043E 0431 0430 0432 043B 0435 043D 0430 0020 043D 0430 0020 0440 0430 0431 043E 0447 0438 0439 0020 0441 0442 043E 043B"
$RunningApplicationError = ConvertFrom-CodePoints "0043 006F 006D 006D 0061 004D 0061 0074 0072 0069 0078 0020 0437 0430 043F 0443 0449 0435 043D 002E 0020 0417 0430 043A 0440 043E 0439 0442 0435 0020 0435 0433 043E 0020 0447 0435 0440 0435 0437 0020 0441 0438 0441 0442 0435 043C 043D 044B 0439 0020 0442 0440 0435 0439 0020 0438 0020 0437 0430 043F 0443 0441 0442 0438 0442 0435 0020 0443 0441 0442 0430 043D 043E 0432 0449 0438 043A 0020 0441 043D 043E 0432 0430 002E"
$RunningApplicationErrorEn = "CommaMatrix is running. Close it from the system tray and run the installer again."

$SecondsUnit = ConvertFrom-CodePoints "0441"
$StepFormat = ConvertFrom-CodePoints "0428 0430 0433 0020 007B 0030 007D 0020 0438 0437 0020 0033"
$InstallingPythonLabel = ConvertFrom-CodePoints "0423 0441 0442 0430 043D 043E 0432 043A 0430 0020 0050 0079 0074 0068 006F 006E"
$DownloadingPythonLabel = ConvertFrom-CodePoints "0417 0430 0433 0440 0443 0437 043A 0430 0020 0050 0079 0074 0068 006F 006E"
$CreatingEnvironmentLabel = ConvertFrom-CodePoints "0421 043E 0437 0434 0430 043D 0438 0435 0020 043E 043A 0440 0443 0436 0435 043D 0438 044F 002E 002E 002E"
$ConfiguringLabel = ConvertFrom-CodePoints "041F 0435 0440 0432 043E 043D 0430 0447 0430 043B 044C 043D 0430 044F 0020 043D 0430 0441 0442 0440 043E 0439 043A 0430 002E 002E 002E"

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

function Wait-WithSpinner {
    param(
        [Parameter(Mandatory = $true)]
        [System.Management.Automation.Job]$Job,
        [Parameter(Mandatory = $true)]
        [string]$Label,
        [string]$Step = "",
        [switch]$StreamOutput
    )

    $display = if ($Step) { "$Step $Label" } else { $Label }
    $frames = @("|", "/", "-", "\")
    $frameIndex = 0
    $startedAt = [DateTime]::UtcNow
    $drained = @()
    while ($Job.State -eq "Running") {
        if ($StreamOutput) {
            $incoming = @(Receive-Job -Job $Job)
            if ($incoming.Count -gt 0) {
                Write-Host ("`r" + (" " * ($display.Length + 24)) + "`r") -NoNewline
                foreach ($item in $incoming) {
                    Write-Host $item
                    $drained += $item
                }
            }
        }
        $elapsed = [int]([DateTime]::UtcNow - $startedAt).TotalSeconds
        $frame = $frames[$frameIndex % $frames.Count]
        Write-Host ("`r{0} {1} ({2}{3})  " -f $frame, $display, $elapsed, $SecondsUnit) -NoNewline
        $frameIndex += 1
        Start-Sleep -Milliseconds 150
    }
    Write-Host ("`r" + (" " * ($display.Length + 24)) + "`r") -NoNewline
    return $drained
}

function Invoke-External {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [Parameter(Mandatory = $true)]
        [string[]]$ArgumentList,
        [switch]$Quiet,
        [string]$Spinner,
        [string]$Step,
        [switch]$StreamOutput
    )

    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $exitCode = 0
    $capturedOutput = @()
    try {
        if ($Spinner) {
            $job = Start-Job -ScriptBlock {
                param($fp, $al, $stream)
                if ($stream) {
                    & $fp @al 2>&1 | ForEach-Object { $_ }
                }
                else {
                    $output = & $fp @al 2>&1
                }
                $code = 1
                if ($null -ne $LASTEXITCODE) {
                    $code = $LASTEXITCODE
                }
                if ($stream) {
                    [pscustomobject]@{ ExitCode = $code }
                }
                else {
                    [pscustomobject]@{ ExitCode = $code; Output = $output }
                }
            } -ArgumentList @($FilePath, $ArgumentList, [bool]$StreamOutput)

            $drained = @(Wait-WithSpinner -Job $job -Label $Spinner -Step $Step -StreamOutput:$StreamOutput)
            $result = Receive-Job -Job $job -Wait
            Remove-Job -Job $job -Force
            $sawResult = $false
            foreach ($item in @($drained) + @($result)) {
                if ($null -eq $item) {
                    continue
                }
                $exitCodeProperty = $item.psobject.Properties["ExitCode"]
                if ($null -ne $exitCodeProperty) {
                    $exitCode = [int]$exitCodeProperty.Value
                    $sawResult = $true
                    $outputProperty = $item.psobject.Properties["Output"]
                    if ($null -ne $outputProperty) {
                        $capturedOutput += @($outputProperty.Value)
                    }
                }
                else {
                    $capturedOutput += $item
                }
            }
            if (-not $sawResult) {
                throw "$FilePath did not report an exit code"
            }
            if ($StreamOutput -and $exitCode -eq 0) {
                foreach ($line in @($capturedOutput | Select-Object -Skip $drained.Count)) {
                    Write-Host $line
                }
            }
        }
        elseif ($Quiet) {
            & $FilePath @ArgumentList *> $null
            $exitCode = $LASTEXITCODE
        }
        else {
            & $FilePath @ArgumentList
            $exitCode = $LASTEXITCODE
        }
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($exitCode -ne 0) {
        $remainingOutput = @($capturedOutput | Select-Object -Skip $drained.Count)
        foreach ($line in $remainingOutput) {
            Write-Host $line
        }
        throw "$FilePath exited with code $exitCode"
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

function Test-CommaMatrixRunning {
    $entrypointPaths = @((Join-Path $InstallRoot "entrypoint.py"))
    $desktopPath = [Environment]::GetFolderPath("Desktop")
    if ([string]::IsNullOrWhiteSpace($desktopPath)) {
        $desktopPath = Join-Path $HOME "Desktop"
    }
    $shortcutPath = Join-Path $desktopPath "CommaMatrix.lnk"
    if (Test-Path -LiteralPath $shortcutPath) {
        $shell = $null
        try {
            $shell = New-Object -ComObject WScript.Shell
            $arguments = [string]$shell.CreateShortcut($shortcutPath).Arguments
            $match = [regex]::Match($arguments, '^\s*"(?<path>[^"]+)"')
            if ($match.Success) {
                $entrypointPaths += $match.Groups["path"].Value
            }
            elseif (-not [string]::IsNullOrWhiteSpace($arguments)) {
                $entrypointPaths += $arguments.Trim()
            }
        }
        catch {
        }
        finally {
            if ($null -ne $shell) {
                [void][Runtime.InteropServices.Marshal]::ReleaseComObject($shell)
            }
        }
    }

    $processes = @(Get-CimInstance -ClassName Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" -ErrorAction SilentlyContinue)
    foreach ($process in $processes) {
        if ([string]::IsNullOrWhiteSpace($process.CommandLine)) {
            continue
        }
        foreach ($entrypointPath in $entrypointPaths) {
            if ($process.CommandLine.IndexOf($entrypointPath, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
                return $true
            }
        }
    }
    return $false
}

try {
    if (Test-CommaMatrixRunning) {
        throw "$RunningApplicationError / $RunningApplicationErrorEn"
    }

    New-Item -ItemType Directory -Path $InstallRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $TempRoot -Force | Out-Null

    $StepOne = $StepFormat -f 1
    $StepTwo = $StepFormat -f 2
    $StepThree = $StepFormat -f 3

    Write-Host "$InstallingLibraries / Installing libraries..."
    $PythonPath = Get-Python313 -Step $StepOne
    Invoke-External -FilePath $PythonPath -Spinner $CreatingEnvironmentLabel -Step $StepTwo -ArgumentList @(
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

    Invoke-External -FilePath $VenvPython -Spinner $InstallingLibraries -Step $StepTwo -StreamOutput -ArgumentList @(
        "-m",
        "pip",
        "install",
        "--upgrade",
        "--progress-bar",
        "off",
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

    try {
        $BootstrapResult = Get-Content -LiteralPath $ResultPath -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    catch {
        throw "Could not read bootstrap result: $($_.Exception.Message)"
    }
    $EntrypointPath = [string]$BootstrapResult.entrypoint
    $PreserveData = [bool]$BootstrapResult.preserve_data
    if ([string]::IsNullOrWhiteSpace($EntrypointPath) -or -not (Test-Path -LiteralPath $EntrypointPath)) {
        throw "Bootstrap did not produce an entrypoint"
    }

    Invoke-External -FilePath $VenvPython -ArgumentList @(
        $EntrypointPath,
        "--initialize",
        "--credentials-file",
        $CredentialsPath
    )
    $AdminCredentials = $null
    if (-not (Test-Path -LiteralPath $CredentialsPath) -and -not $PreserveData) {
        throw "Entrypoint did not produce initial administrator credentials"
    }
    if (Test-Path -LiteralPath $CredentialsPath) {
        try {
            $AdminCredentials = Get-Content -LiteralPath $CredentialsPath -Raw -Encoding UTF8 | ConvertFrom-Json
        }
        catch {
            throw "Could not read initial administrator credentials: $($_.Exception.Message)"
        }
    }
    $AdminUsername = ""
    $AdminPassword = ""
    if ($null -ne $AdminCredentials) {
        $AdminUsername = [string]$AdminCredentials.username
        if ([string]::IsNullOrWhiteSpace($AdminUsername)) {
            throw "Initial administrator credentials do not contain a username"
        }
        $AdminPassword = [string]$AdminCredentials.password
        if ([string]::IsNullOrWhiteSpace($AdminPassword)) {
            throw "Initial administrator credentials do not contain a password"
        }
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
    if (-not (Test-Path -LiteralPath $PersistentLogoPng)) {
        Copy-Item -LiteralPath $LogoPngPath -Destination $PersistentLogoPng
    }
    if (-not (Test-Path -LiteralPath $PersistentLogoIco)) {
        Copy-Item -LiteralPath $LogoIcoPath -Destination $PersistentLogoIco
    }

    New-DesktopShortcut `
        -TargetPath $PythonwPath `
        -EntrypointPath $EntrypointPath `
        -WorkingDirectory $WorkspacePath `
        -IconPath $PersistentLogoIco
    Write-Host "$ShortcutLabel / Launch shortcut was added to desktop"

    Write-Host ""
    Write-Host "========================================"
    if ($null -ne $AdminCredentials) {
        Write-Host "$AdminUsernameLabel / Username:"
        Write-Host $AdminUsername
        Write-Host "$AdminPasswordLabel / Administrator password:"
        Write-Host $AdminPassword
        Write-Host "$SavePasswordLabel / Save this password."
        Write-Host "$ChangeCredentialsLabel / You can change the username and password through the web interface."
    }
    else {
        Write-Host "Existing administrator credentials were preserved."
    }
    Write-Host "========================================"
}
catch {
    $errorRecord = $_
    Write-Host "Installation failed:"
    Write-Host ("Message: " + $errorRecord.Exception.Message)
    Write-Host ("Position: " + $errorRecord.InvocationInfo.PositionMessage)
    exit 1
}
finally {
    if (Test-Path -LiteralPath $TempRoot) {
        Remove-Item -LiteralPath $TempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
    Read-Host "Press Enter to exit"
}
