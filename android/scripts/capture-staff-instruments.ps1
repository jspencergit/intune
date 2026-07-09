<#
.SYNOPSIS
  Automatically tap "Instrument · …" and screenshot each of Viola / Cello / Violin.

  Uses uiautomator dump + adb input tap (Compose nodes often report clickable=false,
  so we tap the text bounds center).

.EXAMPLE
  .\capture-staff-instruments.ps1
#>
param(
    [string]$Serial = "",
    [int]$SettleMs = 500
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\env.ps1"

$adb = Get-IntuneAdb
if (-not $Serial) { $Serial = Get-IntuneDeviceId }
$cap = Join-Path $PSScriptRoot "capture-ui.ps1"
$tmpXml = Join-Path $env:TEMP "intune_ui_dump.xml"

function Get-UiXml {
    & $adb -s $Serial shell uiautomator dump /sdcard/ui.xml | Out-Null
    & $adb -s $Serial pull /sdcard/ui.xml $tmpXml | Out-Null
    return (Get-Content $tmpXml -Raw -Encoding UTF8)
}

function Find-BoundsCenter([string]$xml, [string]$textSubstring) {
    # bounds=[l,t][r,b]
    $pattern = 'text="([^"]*)"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"'
    $matches = [regex]::Matches($xml, $pattern)
    foreach ($m in $matches) {
        $text = $m.Groups[1].Value
        if ($text -like "*$textSubstring*") {
            $l = [int]$m.Groups[2].Value
            $t = [int]$m.Groups[3].Value
            $r = [int]$m.Groups[4].Value
            $b = [int]$m.Groups[5].Value
            return @{
                X = [int](($l + $r) / 2)
                Y = [int](($t + $b) / 2)
                Text = $text
                Bounds = "[$l,$t][$r,$b]"
            }
        }
    }
    # try content-desc
    $pattern2 = 'content-desc="([^"]*)"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"'
    foreach ($m in [regex]::Matches($xml, $pattern2)) {
        if ($m.Groups[1].Value -like "*$textSubstring*") {
            $l = [int]$m.Groups[2].Value; $t = [int]$m.Groups[3].Value
            $r = [int]$m.Groups[4].Value; $b = [int]$m.Groups[5].Value
            return @{ X = [int](($l+$r)/2); Y = [int](($t+$b)/2); Text = $m.Groups[1].Value }
        }
    }
    return $null
}

function Invoke-Tap([int]$x, [int]$y) {
    & $adb -s $Serial shell input tap $x $y
    if ($LASTEXITCODE -ne 0) { throw "tap failed at $x,$y" }
}

Write-Host "Device: $Serial"
Write-Host "Looking for Instrument control (must be on Staff view)..."

$xml = Get-UiXml
$inst = Find-BoundsCenter $xml "Instrument"
if (-not $inst) {
    # Maybe still on Cents view — try tapping Staff first
    $staff = Find-BoundsCenter $xml "Staff"
    if ($staff) {
        Write-Host "Tapping Staff to enter staff view at $($staff.X),$($staff.Y)"
        Invoke-Tap $staff.X $staff.Y
        Start-Sleep -Milliseconds $SettleMs
        $xml = Get-UiXml
        $inst = Find-BoundsCenter $xml "Instrument"
    }
}

if (-not $inst) {
    Write-Host "UI dump texts containing relevant nodes:"
    [regex]::Matches($xml, 'text="([^"]+)"') | ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique | ForEach-Object { Write-Host "  $_" }
    throw "Could not find 'Instrument' control. Put app in Staff view (landscape preferred) and try again."
}

Write-Host "Instrument control: '$($inst.Text)' @ $($inst.X),$($inst.Y) $($inst.Bounds)"

# Cycle until we see each instrument once (max 6 taps)
$wanted = @("Viola", "Cello", "Violin")
$got = @{}
$paths = @()

for ($i = 0; $i -lt 6 -and $got.Count -lt 3; $i++) {
    $xml = Get-UiXml
    $inst = Find-BoundsCenter $xml "Instrument"
    if (-not $inst) { throw "Instrument control disappeared" }

    $name = $null
    foreach ($w in $wanted) {
        if ($inst.Text -like "*$w*") { $name = $w; break }
    }
    if (-not $name) {
        Write-Warning "Unrecognized instrument label: $($inst.Text)"
        $name = "unknown_$i"
    }

    if (-not $got.ContainsKey($name)) {
        Write-Host "Capturing staff_$($name.ToLower()) ..."
        $p = & $cap -Label "staff_$($name.ToLower())" -Serial $Serial
        Write-Host "  -> $p"
        $paths += $p
        $got[$name] = $true
    }

    if ($got.Count -ge 3) { break }

    # Tap to cycle to next instrument
    Write-Host "Tapping to cycle instrument..."
    Invoke-Tap $inst.X $inst.Y
    Start-Sleep -Milliseconds $SettleMs
}

$list = Join-Path (Get-IntuneScreenshotDir) "last_staff_instruments.txt"
$paths | Set-Content $list -Encoding UTF8
Write-Host ""
Write-Host "Done. Captured $($paths.Count) instruments:"
$paths | ForEach-Object { Write-Host "  $_" }
Write-Host "List: $list"
if ($got.Count -lt 3) {
    Write-Warning "Only got: $($got.Keys -join ', ')"
}
