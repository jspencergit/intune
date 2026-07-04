<#
Package Intune Visualizer for Windows distribution.

Creates a portable ZIP (exe + DLLs + quick-start text) and optionally copies it
to the analogintuition.com downloads folder.

Usage:
  .\package.ps1
  .\package.ps1 -Version 0.2.0
  .\package.ps1 -CopyToWebsite
  .\package.ps1 -SkipBuild
#>

param(
    [string]$Version = "0.2.0",
    [switch]$CopyToWebsite,
    [switch]$SkipBuild,
    [string]$WebsiteDownloads = "C:\Code\gitRepos\analogintuition-com\intune\downloads"
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $here

$releaseDir = Join-Path $here "build\Release"
$distDir = Join-Path $here "dist"
$zipName = "Intune-Visualizer-win64-v$Version.zip"
$zipPath = Join-Path $distDir $zipName

Write-Host "=== Intune Visualizer packaging v$Version ===" -ForegroundColor Cyan

if (-not $SkipBuild) {
    & (Join-Path $here "build.ps1")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$required = @("intune_viz.exe", "raylib.dll", "glfw3.dll")
foreach ($f in $required) {
    if (-not (Test-Path (Join-Path $releaseDir $f))) {
        Write-Host "Missing $f in $releaseDir - build Release first." -ForegroundColor Red
        exit 1
    }
}

if (Test-Path $distDir) { Remove-Item -Recurse -Force $distDir }
New-Item -ItemType Directory -Path $distDir | Out-Null
$stage = Join-Path $distDir "Intune"
New-Item -ItemType Directory -Path $stage | Out-Null

foreach ($f in $required) {
    Copy-Item (Join-Path $releaseDir $f) $stage
}

$readme = (@(
    "Intune Visualizer for Windows (v$Version)",
    "=========================================",
    "",
    "QUICK START (no hardware - built-in simulator)",
    "  1. Extract this entire folder anywhere.",
    "  2. Double-click intune_viz.exe",
    "     (or: .\intune_viz.exe --simulate)",
    "",
    "WITH TEENSY PITCH SENSOR",
    "  1. Flash firmware from the Intune repo (teensy/ folder).",
    "  2. Connect Teensy USB; note COM port in Device Manager.",
    "  3. Run:  intune_viz.exe --port COM3  (default baud 230400)",
    "",
    "MORE INFO: https://analogintuition.com/intune/"
) -join "`r`n")
Set-Content -Path (Join-Path $stage "README.txt") -Value $readme -Encoding UTF8

if (Test-Path $zipPath) { Remove-Item -Force $zipPath }
Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zipPath -Force

$sizeMb = [math]::Round((Get-Item $zipPath).Length / 1MB, 2)
Write-Host "`nCreated: $zipPath ($($sizeMb) MB)" -ForegroundColor Green

if ($CopyToWebsite) {
    New-Item -ItemType Directory -Path $WebsiteDownloads -Force | Out-Null
    Copy-Item $zipPath $WebsiteDownloads -Force
    Write-Host "Copied to: $WebsiteDownloads\$zipName" -ForegroundColor Green
    Write-Host "Commit and push analogintuition-com to publish the download." -ForegroundColor Yellow
}

Pop-Location