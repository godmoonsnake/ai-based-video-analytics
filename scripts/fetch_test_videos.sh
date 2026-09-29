#!/usr/bin/env bash
# Fetch public test videos for the DARSON real-video Frigate development path.
#
# Downloads person-detection sample clips from the archived Intel IoT DevKit
# sample-videos repository (license: CC-BY-4.0 — attribution required). These
# are NOT committed to Git; they are fetched on demand into deploy/videos/
# (gitignored).
#
# Usage:  ./scripts/fetch_test_videos.sh
set -euo pipefail
cd "$(dirname "$0")/.."

dir="deploy/videos"
mkdir -p "$dir"
base="https://github.com/intel-iot-devkit/sample-videos/raw/master"
videos=(people-detection.mp4 store-aisle-detection.mp4 one-by-one-person-detection.mp4)

for v in "${videos[@]}"; do
  if [ -f "$dir/$v" ]; then echo "  exists: $v"; continue; fi
  echo "  downloading: $v"
  curl -fsSL "$base/$v" -o "$dir/$v"
done

cat > "$dir/ATTRIBUTION.txt" <<'EOF'
Test videos for the DARSON real-video development path.

Source:  https://github.com/intel-iot-devkit/sample-videos  (archived)
License: CC-BY-4.0 (Creative Commons Attribution 4.0)
         Attribution: Intel IoT DevKit sample-videos.
Usage:   Development/demonstration only. These files are fetched on demand and
         are NOT committed to this repository (see .gitignore: deploy/videos/).
EOF

echo "Done. Videos in $dir (gitignored)."
