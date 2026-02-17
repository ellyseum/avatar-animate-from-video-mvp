#!/bin/bash
# Watch the latest FrankMocap CI build and notify on completion.
# Usage: ./scripts/watch-ci.sh [run-id]
# If no run-id given, watches the most recent run.

set -euo pipefail

RUN_ID="${1:-$(gh run list --workflow=build-frankmocap.yml --limit 1 --json databaseId -q '.[0].databaseId')}"

if [ -z "$RUN_ID" ]; then
    echo "No CI runs found"
    exit 1
fi

echo "Watching run $RUN_ID..."
echo "https://github.com/ellyseum/avatar-animate-from-video-mvp/actions/runs/$RUN_ID"

# FF Victory Fanfare
play_victory() {
    powershell.exe -c "[console]::beep(523,150);[console]::beep(523,150);[console]::beep(523,150);[console]::beep(523,400);Start-Sleep -m 50;[console]::beep(415,400);[console]::beep(466,400);[console]::beep(523,150);Start-Sleep -m 50;[console]::beep(466,150);[console]::beep(523,500);" 2>/dev/null &
}

# Sad trombone
play_fail() {
    powershell.exe -c "[console]::beep(392,500);[console]::beep(370,500);[console]::beep(349,500);[console]::beep(330,1000);" 2>/dev/null &
}

if gh run watch "$RUN_ID" --exit-status; then
    play_victory
    powershell.exe -Command "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.MessageBox]::Show('Build complete! Run: npm run frank:pull','FrankMocap CI','OK','Information')" 2>/dev/null
    echo -e "\n✓ Build succeeded! Run: npm run frank:pull"
else
    play_fail
    powershell.exe -Command "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.MessageBox]::Show('Build FAILED','FrankMocap CI','OK','Error')" 2>/dev/null
    echo -e "\n✗ Build failed. Check: gh run view $RUN_ID --log-failed"
fi
