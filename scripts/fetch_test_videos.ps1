# Fetch public test videos for the DARSON real-video Frigate development path.
#
# Downloads a small set of person-detection sample clips from the archived Intel
# IoT DevKit sample-videos repository (license: CC-BY-4.0 — attribution required;
# see deploy/videos/ATTRIBUTION.txt written below). These are NOT committed to
# Git; they are fetched on demand into deploy/videos/ (gitignored).
#
# Usage:  .\scripts\fetch_test_videos.ps1
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$dir = "deploy/videos"
New-Item -ItemType Directory -Force -Path $dir | Out-Null

$base = "https://github.com/intel-iot-devkit/sample-videos/raw/master"
# Three clips -> three "cameras" for the multi-camera movement scenario.
$videos = @(
    "people-detection.mp4",
    "store-aisle-detection.mp4",
    "one-by-one-person-detection.mp4"
)

foreach ($v in $videos) {
    $dest = Join-Path $dir $v
    if (Test-Path $dest) { Write-Host "  exists: $v"; continue }
    Write-Host "  downloading: $v"
    Invoke-WebRequest -Uri "$base/$v" -OutFile $dest
}

@"
Test videos for the DARSON real-video development path.

Source:  https://github.com/intel-iot-devkit/sample-videos  (archived)
License: CC-BY-4.0 (Creative Commons Attribution 4.0)
         Attribution: Intel IoT DevKit sample-videos.
Usage:   Development/demonstration only. These files are fetched on demand and
         are NOT committed to this repository (see .gitignore: deploy/videos/).
"@ | Set-Content -Path (Join-Path $dir "ATTRIBUTION.txt")

Write-Host "Done. Videos in $dir (gitignored). Attribution written to $dir/ATTRIBUTION.txt"
