<#
.SYNOPSIS
  Capture the connected Android phone screen into android/screenshots/

.PARAMETER Label
  Short name baked into the filename (e.g. cents_portrait, staff_landscape)

.PARAMETER Serial
  Optional adb device serial

.EXAMPLE
  .\capture-ui.ps1 -Label cents_portrait
  .\capture-ui.ps1 -Label staff_landscape_mid_scale
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$Label,
    [string]$Serial = ""
)

. "$PSScriptRoot\env.ps1"

$adb = Get-IntuneAdb
if (-not $Serial) { $Serial = Get-IntuneDeviceId }
$dir = Get-IntuneScreenshotDir

$safe = ($Label -replace '[^\w\-]+', '_').Trim('_')
if (-not $safe) { $safe = "shot" }
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$name = "${stamp}_${safe}.png"
$path = Join-Path $dir $name

# Binary PNG to file (PowerShell-safe)
$tmpOnDevice = "/sdcard/intune_ui_cap.png"
& $adb -s $Serial shell screencap -p $tmpOnDevice
if ($LASTEXITCODE -ne 0) { throw "screencap failed (exit $LASTEXITCODE)" }
& $adb -s $Serial pull $tmpOnDevice $path | Out-Null
& $adb -s $Serial shell rm $tmpOnDevice | Out-Null

if (-not (Test-Path $path) -or (Get-Item $path).Length -lt 1000) {
    throw "Screenshot missing or too small: $path"
}

Write-Output $path
