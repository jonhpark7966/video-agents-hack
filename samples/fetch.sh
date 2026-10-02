#!/usr/bin/env bash
# Re-download the sample clips locally. The videos are third-party footage,
# so they stay out of git (see .gitignore); this script is the source of truth.
set -euo pipefail
cd "$(dirname "$0")"

clip() { # <youtube id> <start> <end> <output>
  yt-dlp -f "bv*[ext=mp4][height<=1080]+ba[ext=m4a]/b" --merge-output-format mp4 \
    --download-sections "*$2-$3" --force-keyframes-at-cuts -o "$4" "https://youtu.be/$1"
}

# Input: Rodrigo Muniz goal, Sheff Utd 3-3 Fulham 2023/24 (Premier League, "1 HOUR of the Premier League's BEST Goals")
clip wz1r_VJaJZw 58:36 59:14 wz1r_VJaJZw_5836-5914.mp4

# Reference output: tactical overlay style (DK FALCON, "How a Team of Nobodies Achieved What Superstars Couldn't")
clip g1nYknl92wI 8:42 8:52 g1nYknl92wI_0842-0852.mp4
