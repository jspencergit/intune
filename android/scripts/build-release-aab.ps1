<#
.SYNOPSIS
  Build a signed Play App Bundle (AAB) for Internal testing upload.
#>
$ErrorActionPreference = "Stop"
$androidRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $androidRoot

$props = Join-Path $androidRoot "keystore.properties"
$jks = Join-Path $androidRoot "upload-keystore.jks"
if (-not (Test-Path $props) -or -not (Test-Path $jks)) {
    throw "Missing keystore. Run: .\scripts\create-upload-keystore.ps1"
}

$env:ANDROID_HOME = if ($env:ANDROID_HOME) { $env:ANDROID_HOME } else { "$env:LOCALAPPDATA\Android\Sdk" }
$env:JAVA_HOME = if ($env:JAVA_HOME) { $env:JAVA_HOME } else { "C:\Program Files\Android\Android Studio\jbr" }

$gradle = Get-Command gradle -ErrorAction SilentlyContinue
if (-not $gradle) {
    $gradleBat = Get-ChildItem "$env:USERPROFILE\.gradle\wrapper\dists\gradle-*\*\gradle-*\bin\gradle.bat" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | Select-Object -First 1
    if (-not $gradleBat) { throw "gradle not found on PATH or in ~/.gradle/wrapper/dists" }
    $gradleCmd = $gradleBat.FullName
} else {
    $gradleCmd = $gradle.Source
}

Write-Host "Building signed release AAB..."
& $gradleCmd bundleRelease
if ($LASTEXITCODE -ne 0) { throw "bundleRelease failed" }

$aab = Join-Path $androidRoot "app\build\outputs\bundle\release\app-release.aab"
if (-not (Test-Path $aab)) { throw "AAB not found at $aab" }
Write-Host ""
Write-Host "OK: $aab"
Write-Host "Upload this file in Play Console → Testing → Internal testing → Create release."
