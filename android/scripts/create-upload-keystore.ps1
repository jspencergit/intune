<#
.SYNOPSIS
  Create a Play upload keystore + android/keystore.properties for release builds.

.NOTES
  - Back up upload-keystore.jks and the passwords offline (password manager + USB).
  - Losing them makes updating the Play app painful.
  - Never commit keystore.properties or *.jks.
#>
$ErrorActionPreference = "Stop"
$androidRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$keystorePath = Join-Path $androidRoot "upload-keystore.jks"
$propsPath = Join-Path $androidRoot "keystore.properties"
$alias = "intune_upload"

if (Test-Path $keystorePath) {
    Write-Host "Already exists: $keystorePath"
    Write-Host "Delete it only if you intend to replace the upload key (breaks Play updates if already uploaded)."
    exit 1
}

$keytool = $null
$candidates = @(
    (Join-Path $env:JAVA_HOME "bin\keytool.exe"),
    "C:\Program Files\Android\Android Studio\jbr\bin\keytool.exe",
    "C:\Program Files\Java\*\bin\keytool.exe"
)
foreach ($c in $candidates) {
    $resolved = Get-Item $c -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($resolved) { $keytool = $resolved.FullName; break }
}
if (-not $keytool) {
    $cmd = Get-Command keytool -ErrorAction SilentlyContinue
    if ($cmd) { $keytool = $cmd.Source }
}
if (-not $keytool) { throw "keytool not found. Install JDK or Android Studio JBR." }

Write-Host "Using keytool: $keytool"
Write-Host ""
Write-Host "You will set TWO passwords (store + key). They can be the same."
Write-Host "Save them in a password manager. You need them for every Play update."
Write-Host ""

$secureStore = Read-Host "Keystore (store) password" -AsSecureString
$secureKey = Read-Host "Key password (Enter = same as store)" -AsSecureString
$bstr1 = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureStore)
$storePass = [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr1)
[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr1)
$bstr2 = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
$keyPass = [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr2)
[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr2)
if ([string]::IsNullOrWhiteSpace($keyPass)) { $keyPass = $storePass }
if ($storePass.Length -lt 6) { throw "Store password must be at least 6 characters." }

$cn = Read-Host "Your name (CN) [default: Intune Developer]"
if ([string]::IsNullOrWhiteSpace($cn)) { $cn = "Intune Developer" }
$org = Read-Host "Organization [default: Analog Intuition]"
if ([string]::IsNullOrWhiteSpace($org)) { $org = "Analog Intuition" }

$dname = "CN=$cn, OU=Mobile, O=$org, L=Unknown, ST=Unknown, C=US"

Write-Host ""
Write-Host "Creating $keystorePath ..."
& $keytool -genkeypair `
    -v `
    -keystore $keystorePath `
    -alias $alias `
    -keyalg RSA `
    -keysize 2048 `
    -validity 10000 `
    -storepass $storePass `
    -keypass $keyPass `
    -dname $dname
if ($LASTEXITCODE -ne 0) { throw "keytool failed" }

@"
storeFile=upload-keystore.jks
storePassword=$storePass
keyAlias=$alias
keyPassword=$keyPass
"@ | Set-Content -Path $propsPath -Encoding UTF8

Write-Host ""
Write-Host "Done."
Write-Host "  Keystore: $keystorePath"
Write-Host "  Config:   $propsPath"
Write-Host "  Alias:    $alias"
Write-Host ""
Write-Host "NEXT: back up the .jks + passwords offline, then build:"
Write-Host "  cd android"
Write-Host "  # with Gradle:"
Write-Host "  .\.. path-to-gradle bundleRelease"
Write-Host "  AAB lands in app\build\outputs\bundle\release\app-release.aab"
Write-Host ""
Write-Host "Never commit upload-keystore.jks or keystore.properties."
