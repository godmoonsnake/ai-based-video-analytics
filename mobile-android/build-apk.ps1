$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $env:JAVA_HOME) { throw 'Set JAVA_HOME to JDK 17 before building.' }
if (-not ($env:ANDROID_SDK_ROOT -or $env:ANDROID_HOME)) {
    throw 'Set ANDROID_SDK_ROOT or ANDROID_HOME to your Android SDK.'
}

# Keep generated resources off OneDrive to avoid Windows sync file locks.
$env:DARSON_ANDROID_BUILD_DIR = Join-Path ([IO.Path]::GetTempPath()) 'darson-guard-apk-build'
& (Join-Path $project 'gradlew.bat') ':app:assembleDebug' '--no-daemon' '--console=plain'
if ($LASTEXITCODE -ne 0) { throw 'Android APK build failed.' }

$built = Join-Path $env:DARSON_ANDROID_BUILD_DIR 'outputs\apk\debug\app-debug.apk'
if (-not (Test-Path -LiteralPath $built)) { throw 'Gradle did not produce an APK.' }
$output = Join-Path $project 'DARSON-Guard-preview.apk'
Copy-Item -LiteralPath $built -Destination $output -Force
Write-Output "Installable test APK: $output"
