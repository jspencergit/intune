# Shared paths for Intune Android UI capture scripts.
# Dot-source:  . "$PSScriptRoot\env.ps1"

$ErrorActionPreference = "Stop"

$script:IntuneRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$script:AdbCandidates = @(
    "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe",
    "$env:ANDROID_HOME\platform-tools\adb.exe",
    "$env:ANDROID_SDK_ROOT\platform-tools\adb.exe"
)

function Get-IntuneAdb {
    foreach ($p in $script:AdbCandidates) {
        if ($p -and (Test-Path $p)) { return $p }
    }
    $cmd = Get-Command adb -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    throw "adb not found. Install Android SDK platform-tools or add adb to PATH."
}

function Get-IntuneDeviceId {
    param([string]$Adb = (Get-IntuneAdb))
    # Force array — a single match is a [string], and $s[0] is the first character.
    $lines = @(& $Adb devices 2>&1 | Where-Object { $_ -match "device$" -and $_ -notmatch "List of devices" -and $_ -notmatch "offline|unauthorized" })
    if (-not $lines -or $lines.Count -eq 0) {
        throw "No Android device in 'device' state. Plug in USB, enable debugging, accept RSA prompt."
    }
    $id = ($lines[0] -split "\s+")[0].Trim()
    if (-not $id -or $id.Length -lt 4) {
        throw "Failed to parse adb device id from: $($lines[0])"
    }
    return $id
}

function Get-IntuneScreenshotDir {
    $dir = Join-Path $script:IntuneRoot "android\screenshots"
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    return $dir
}

function Get-IntuneAudioDevice {
    $f = Join-Path $script:IntuneRoot "teensy\tools\audio_device.txt"
    if (Test-Path $f) {
        $line = (Get-Content $f -TotalCount 1).Trim()
        if ($line -match '^\d+$') { return [int]$line }
    }
    return 5  # Chat 150 default on this machine
}
