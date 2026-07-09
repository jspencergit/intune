<#
.SYNOPSIS
  Play a test scale/tones (Chat150 → mic → Teensy → BLE → app) and grab screenshots.

.PARAMETER Label
  Prefix for screenshot names (include mode hints: cents, staff, portrait, landscape)

.PARAMETER Audio
  Path to audio file (mp3/wav). Default: synthetic viola C major updown perfect.

.PARAMETER Tones
  Comma-separated notes instead of a file, e.g. "A4,C4,E4,C3"

.PARAMETER NoteSec
  Seconds per tone when using -Tones

.PARAMETER Gain
  Playback gain 0–1

.PARAMETER CaptureAt
  Comma-separated fractions of playback (0–1) to capture. Default: mid + near end.
  Example: "0.15,0.5,0.85"

.PARAMETER CaptureStart
  Also capture once before playback starts

.PARAMETER CaptureEnd
  Also capture once after playback ends

.EXAMPLE
  # User set app to Cents + Portrait; run scale and grab mid/end shots
  .\play-and-capture.ps1 -Label cents_portrait

  # Staff landscape after user rotates + toggles staff view
  .\play-and-capture.ps1 -Label staff_landscape -CaptureAt "0.25,0.5,0.75"
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$Label,
    [string]$Audio = "",
    [string]$Tones = "",
    [double]$NoteSec = 1.0,
    [double]$Gain = 0.75,
    [string]$CaptureAt = "0.40,0.80",
    [switch]$CaptureStart,
    [switch]$CaptureEnd,
    [int]$Device = -1,
    [string]$Serial = ""
)

. "$PSScriptRoot\env.ps1"

$adb = Get-IntuneAdb
if (-not $Serial) { $Serial = Get-IntuneDeviceId }
if ($Device -lt 0) { $Device = Get-IntuneAudioDevice }

$capScript = Join-Path $PSScriptRoot "capture-ui.ps1"
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { throw "python not found on PATH" }

function Invoke-Capture([string]$suffix) {
    $p = & $capScript -Label "${Label}_${suffix}" -Serial $Serial
    Write-Host "[capture] $p"
    return $p
}

# Resolve audio
$defaultAudio = Join-Path $script:IntuneRoot "test_audio\synthetic_C_major_scale_updown_viola_perfect.mp3"
if (-not $Audio -and -not $Tones) {
    if (Test-Path $defaultAudio) { $Audio = $defaultAudio }
    else { $Tones = "C3,E3,G3,C4,E4,G4,C5,A4" }
}

$paths = @()
if ($CaptureStart) { $paths += Invoke-Capture "start" }

# Build a small Python driver that plays + signals capture times via stdout markers
$fracs = @($CaptureAt.Split(",") | ForEach-Object { [double]$_.Trim() } | Where-Object { $_ -gt 0 -and $_ -lt 1 })
$fracsJson = ($fracs | ConvertTo-Json -Compress)
if (-not $fracsJson.StartsWith("[")) { $fracsJson = "[$fracsJson]" }

$driver = @"
import json, sys, time, threading
import numpy as np
import sounddevice as sd

device = $Device
gain = $Gain
fracs = json.loads('$fracsJson')
markers = []

def emit(tag):
    print(f'CAPTURE {tag}', flush=True)

if r'''$Tones'''.strip():
    # tone sequence
    notes = [x.strip() for x in r'''$Tones'''.split(',') if x.strip()]
    note_sec = $NoteSec
    sr = 44100
    pc = {'C':0,'C#':1,'D':2,'D#':3,'E':4,'F':5,'F#':6,'G':7,'G#':8,'A':9,'A#':10,'B':11}
    def freq(n):
        import re
        m = re.fullmatch(r'([A-G]#?)(-?\d+)', n)
        midi = (int(m.group(2))+1)*12 + pc[m.group(1)]
        return 440.0 * (2.0 ** ((midi-69)/12.0))
    chunks = []
    for n in notes:
        f = freq(n)
        n_samp = int(note_sec * sr)
        t = np.arange(n_samp)/sr
        y = np.sin(2*np.pi*f*t).astype(np.float32) * gain
        fade = max(1, int(0.01*sr))
        y[:fade] *= np.linspace(0,1,fade)
        y[-fade:] *= np.linspace(1,0,fade)
        chunks.append(y)
    audio = np.concatenate(chunks)
    sr_out = sr
    total = len(audio)/sr_out
    print(f'PLAY tones n={len(notes)} dur={total:.1f}s device={device}', flush=True)
else:
    path = r'''$Audio'''
    try:
        import soundfile as sf
        data, sr_out = sf.read(path, always_2d=False)
        if data.ndim > 1: data = data.mean(axis=1)
        audio = (data.astype(np.float32) * gain)
    except Exception:
        import librosa
        audio, sr_out = librosa.load(path, sr=None, mono=True)
        audio = (audio.astype(np.float32) * gain)
    total = len(audio)/sr_out
    print(f'PLAY file dur={total:.1f}s device={device}', flush=True)

for f in fracs:
    markers.append((f * total, f'at_{int(f*100):02d}'))

sd.play(audio, sr_out, device=device, blocking=False)
t0 = time.perf_counter()
mi = 0
while True:
    now = time.perf_counter() - t0
    while mi < len(markers) and now >= markers[mi][0]:
        emit(markers[mi][1])
        mi += 1
    if now >= total + 0.05:
        break
    time.sleep(0.05)
sd.wait()
sd.stop()
print('PLAY done', flush=True)
"@

$tmpPy = Join-Path $env:TEMP "intune_play_capture_driver.py"
Set-Content -Path $tmpPy -Value $driver -Encoding UTF8

Write-Host "[play] device=$Device label=$Label serial=$Serial"
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $py.Source
$psi.Arguments = "`"$tmpPy`""
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$psi.UseShellExecute = $false
$psi.CreateNoWindow = $true
$proc = New-Object System.Diagnostics.Process
$proc.StartInfo = $psi
[void]$proc.Start()

# Read stdout line by line and capture on markers
while (-not $proc.HasExited -or -not $proc.StandardOutput.EndOfStream) {
    $line = $proc.StandardOutput.ReadLine()
    if ($null -eq $line) {
        if ($proc.HasExited) { break }
        Start-Sleep -Milliseconds 20
        continue
    }
    Write-Host $line
    if ($line -match '^CAPTURE\s+(\S+)') {
        $tag = $Matches[1]
        try {
            $paths += Invoke-Capture $tag
        } catch {
            Write-Warning "capture failed: $_"
        }
    }
}
$err = $proc.StandardError.ReadToEnd()
if ($err) { Write-Host $err }
$proc.WaitForExit()
if ($proc.ExitCode -ne 0) {
    Write-Warning "playback driver exit code $($proc.ExitCode)"
}

if ($CaptureEnd) { $paths += Invoke-Capture "end" }

Write-Host ""
Write-Host "=== Screenshots ($($paths.Count)) ==="
$paths | ForEach-Object { Write-Host $_ }
# Machine-readable list for the agent
$listPath = Join-Path (Get-IntuneScreenshotDir) "last_capture_list.txt"
$paths | Set-Content -Path $listPath -Encoding UTF8
Write-Host "List: $listPath"
