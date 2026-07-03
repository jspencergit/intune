<#
Intune Raylib Visualizer — Quick Build Helper (Windows PowerShell)

Usage examples:
  .\build.ps1                 # tries cmake + vcpkg if available, otherwise gives guidance
  .\build.ps1 -Simulate       # build + immediately run in simulate mode

This is a helper, not magic. The authoritative instructions are in README.md.
#>

param(
    [switch]$Simulate,
    [switch]$Clean,
    [string]$VcpkgRoot = "C:\vcpkg"
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $here

Write-Host "=== Intune Raylib Visualizer build helper ===" -ForegroundColor Cyan

function Find-CMake {
    $c = Get-Command cmake -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    $candidates = @(
        "C:\Program Files\CMake\bin\cmake.exe",
        "C:\Program Files (x86)\CMake\bin\cmake.exe"
    )
    foreach ($p in $candidates) { if (Test-Path $p) { return $p } }
    return $null
}

function Find-Vcpkg {
    $v = Get-Command vcpkg -ErrorAction SilentlyContinue
    if ($v) { return (Split-Path $v.Source) }
    $p = Join-Path $VcpkgRoot "vcpkg.exe"
    if (Test-Path $p) { return $VcpkgRoot }
    return $null
}

$cmake = Find-CMake
if (-not $cmake) {
    Write-Host "CMake not found on PATH or in standard locations." -ForegroundColor Yellow
    Write-Host "Install CMake or add it to PATH, then re-run." -ForegroundColor Yellow
    Write-Host "Alternatively follow the MSYS2 instructions in README.md (often the easiest on Windows)." -ForegroundColor Yellow
    exit 1
}

Write-Host "CMake: $cmake"

$vcpkg = Find-Vcpkg
$toolchain = $null
if ($vcpkg) {
    $toolchain = Join-Path $vcpkg "scripts\buildsystems\vcpkg.cmake"
    if (-not (Test-Path $toolchain)) { $toolchain = $null }
}

$buildDir = "build"
if ($Clean -and (Test-Path $buildDir)) {
    Write-Host "Cleaning $buildDir..."
    Remove-Item -Recurse -Force $buildDir
}

New-Item -ItemType Directory -Path $buildDir -ErrorAction SilentlyContinue | Out-Null

if ($toolchain) {
    Write-Host "Using vcpkg toolchain: $toolchain" -ForegroundColor Green
    & $cmake -B $buildDir -S . -DCMAKE_TOOLCHAIN_FILE="$toolchain" -DCMAKE_BUILD_TYPE=Release
} else {
    Write-Host "No vcpkg toolchain detected — using plain CMake (you must have raylib installed via system or -DRAYLIB_DIR)." -ForegroundColor Yellow
    & $cmake -B $buildDir -S . -DCMAKE_BUILD_TYPE=Release
}

if ($LASTEXITCODE -ne 0) {
    Write-Host "`nCMake configure failed. See README.md for alternative build methods (MSYS2 / manual raylib)." -ForegroundColor Red
    exit 1
}

Write-Host "`nBuilding..."
& $cmake --build $buildDir --config Release --parallel

if ($LASTEXITCODE -ne 0) {
    Write-Host "`nBuild failed." -ForegroundColor Red
    exit 1
}

$exe = Join-Path $buildDir "Release\intune_viz.exe"
if (-not (Test-Path $exe)) {
    # Some generators put it directly in build/
    $exe = Join-Path $buildDir "intune_viz.exe"
}

if (Test-Path $exe) {
    Write-Host "`nBuild succeeded: $exe" -ForegroundColor Green

    if ($Simulate) {
        Write-Host "`nLaunching simulator..." -ForegroundColor Cyan
        & $exe --simulate
    } else {
        Write-Host "`nTo run simulator now:   $exe --simulate" -ForegroundColor Cyan
        Write-Host "To run with hardware:  $exe --port COM3" -ForegroundColor Cyan
    }
} else {
    Write-Host "Build appeared to succeed but could not locate the executable. Check the build folder." -ForegroundColor Yellow
}

Pop-Location
