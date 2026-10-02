#!/usr/bin/env bash
# Re-download the sample clips. The videos are third-party footage,
# committed under permission; this script records where they came from.
set -euo pipefail
cd "$(dirname "$0")"

clip() { # <youtube id> <start> <end> <output>
  yt-dlp -f "bv*[vcodec^=avc1][height<=1080][protocol=https]+ba[ext=m4a]/b" --merge-output-format mp4 \
    --download-sections "*$2-$3" --force-keyframes-at-cuts -o "$4" "https://youtu.be/$1"
}

# Input: Rodrigo Muniz goal, Sheff Utd 3-3 Fulham 2023/24 (Premier League, "1 HOUR of the Premier League's BEST Goals")
clip wz1r_VJaJZw 58:36 59:14 wz1r_VJaJZw_5836-5914.mp4

# Reference output: tactical overlay style (DK FALCON, "How a Team of Nobodies Achieved What Superstars Couldn't")
clip g1nYknl92wI 8:42 8:52 g1nYknl92wI_0842-0852.mp4

# Upload sample for the VSS pipeline: Duke vs UCLA, NCAA Championship second round (Jomboy Media, "Duke soccer player mocks goalie and gets decked, a breakdown")
clip ZlnY82npUsA 1:49 1:59 ZlnY82npUsA_0149-0159.mp4

# Fast test slice: the first 8 seconds of the input clip.
ffmpeg -y -i wz1r_VJaJZw_5836-5914.mp4 -t 8 -c:v libx264 -preset veryfast -crf 20 \
  -pix_fmt yuv420p -c:a aac -b:a 128k -movflags +faststart wz1r_VJaJZw_0-8.mp4
