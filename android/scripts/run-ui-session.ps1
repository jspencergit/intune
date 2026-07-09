<#
.SYNOPSIS
  Guided multi-mode Android UI capture session.

  Pauses and asks the human to set the app mode (cents/staff, portrait/landscape),
  then plays audio and grabs screenshots automatically.

.PARAMETER SkipPrompt
  If set, does not pause between modes (use only when modes already match defaults).

.EXAMPLE
  .\run-ui-session.ps1
#>
param(
    [switch]$SkipPrompt,
    [double]$Gain = 0.75
)

. "$PSScriptRoot\env.ps1"

$play = Join-Path $PSScriptRoot "play-and-capture.ps1"
$adb = Get-IntuneAdb
$serial = Get-IntuneDeviceId

Write-Host ""
Write-Host "=== Intune Android UI session ==="
Write-Host "Device: $serial"
Write-Host "adb:    $adb"
Write-Host "Speaker device index: $(Get-IntuneAudioDevice) (teensy/tools/audio_device.txt)"
Write-Host ""
Write-Host "Prereqs (you):"
Write-Host "  1. Phone USB debugging on, app Intune Stream running"
Write-Host "  2. BLE connected to ESP32 (Intune)"
Write-Host "  3. Teensy powered with mic + SD wire solid"
Write-Host "  4. Chat 150 (or pinned speaker) near mic"
Write-Host ""

function Wait-Mode([string]$instruction) {
    if ($SkipPrompt) { return }
    Write-Host ""
    Write-Host ">>> ACTION REQUIRED <<<" -ForegroundColor Yellow
    Write-Host $instruction -ForegroundColor Yellow
    Write-Host "Press Enter when the phone is ready..." -ForegroundColor Yellow
    [void](Read-Host)
}

$all = @()

# --- Mode 1: Cents + Portrait ---
Wait-Mode @"
On the phone:
  - Portrait orientation
  - Cents view (not Staff)
  - Connected to BLE, live scrolling (not paused)
"@
& $play -Label "cents_portrait" -Gain $Gain -CaptureStart -CaptureEnd -CaptureAt "0.35,0.70" -Serial $serial
$all += Get-Content (Join-Path (Get-IntuneScreenshotDir) "last_capture_list.txt")

# --- Mode 2: Staff + Portrait ---
Wait-Mode @"
On the phone:
  - Stay in Portrait
  - Switch to Staff view
  - Instrument Viola (or your target)
  - Live scrolling
"@
& $play -Label "staff_portrait" -Gain $Gain -CaptureStart -CaptureEnd -CaptureAt "0.35,0.70" -Serial $serial
$all += Get-Content (Join-Path (Get-IntuneScreenshotDir) "last_capture_list.txt")

# --- Mode 3: Cents + Landscape ---
Wait-Mode @"
On the phone:
  - Rotate to Landscape
  - Cents view
  - Live scrolling
"@
& $play -Label "cents_landscape" -Gain $Gain -CaptureStart -CaptureEnd -CaptureAt "0.35,0.70" -Serial $serial
$all += Get-Content (Join-Path (Get-IntuneScreenshotDir) "last_capture_list.txt")

# --- Mode 4: Staff + Landscape ---
Wait-Mode @"
On the phone:
  - Stay Landscape
  - Staff view
  - Live scrolling
"@
& $play -Label "staff_landscape" -Gain $Gain -CaptureStart -CaptureEnd -CaptureAt "0.35,0.70" -Serial $serial
$all += Get-Content (Join-Path (Get-IntuneScreenshotDir) "last_capture_list.txt")

$master = Join-Path (Get-IntuneScreenshotDir) "last_session_list.txt"
$all | Set-Content $master -Encoding UTF8

Write-Host ""
Write-Host "=== Session complete ===" -ForegroundColor Green
Write-Host "Screenshots listed in: $master"
Write-Host "Tell Grok: review android/screenshots from last session"
