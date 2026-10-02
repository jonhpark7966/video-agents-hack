#!/bin/sh
# review.sh ITER_DIR PYTHON  -> ITER_DIR/review/{out_*.jpg,wave.png}
D=$1; PY=${2:-python3}
mkdir -p $D/review
DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 $D/hype.mp4)
for s in $(python3 -c "import math;d=$DUR;print(' '.join(str(round(i*4.8,1)) for i in range(math.ceil(d/4.8))))"); do
  e=$(python3 -c "print(min($s+4.8,$DUR-0.05))")
  $PY "$(dirname $0)/sheet.py" $D/hype.mp4 $D/review/out_$s.jpg --start $s --end $e --fps 5 --cols 4 --width 480
done
ffmpeg -y -v error -i $D/hype.mp4 -filter_complex "showwavespic=s=1900x260:split_channels=0:colors=cyan" -frames:v 1 $D/review/wave.png
ls $D/review
