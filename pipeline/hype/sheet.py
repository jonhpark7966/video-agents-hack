"""Contact sheets for looking at a clip frame by frame.

  python sheet.py VIDEO OUT.jpg --start 6 --end 9 --fps 4 [--cols 3] [--width 640] [--grid]

Each tile carries its time stamp and source frame number. With --grid, a 10%
grid with labels is drawn so positions can be read off as normalized x/y.
"""

import argparse

import cv2
from PIL import Image, ImageDraw, ImageFont

FONT = "/System/Library/Fonts/Helvetica.ttc"


def frames_at(video, times):
    cap = cv2.VideoCapture(video)
    fps = cap.get(cv2.CAP_PROP_FPS)
    out = []
    for t in times:
        index = int(round(t * fps))
        cap.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = cap.read()
        if ok:
            out.append((t, index, frame))
    cap.release()
    return out, fps


def sheet(video, out, start, end, fps, cols=3, width=640, grid=False, crop=None):
    count = max(1, int(round((end - start) * fps)))
    times = [start + i / fps for i in range(count)]
    frames, _ = frames_at(video, times)
    tiles = []
    font = ImageFont.truetype(FONT, 22)
    small = ImageFont.truetype(FONT, 13)
    for t, index, frame in frames:
        h, w = frame.shape[:2]
        if crop:
            x0, y0, x1, y1 = crop
            frame = frame[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]
        img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        img = img.resize((width, int(width * img.height / img.width)))
        draw = ImageDraw.Draw(img, "RGBA")
        if grid:
            for k in range(1, 10):
                x = img.width * k / 10
                y = img.height * k / 10
                draw.line([(x, 0), (x, img.height)], fill=(255, 255, 255, 70))
                draw.line([(0, y), (img.width, y)], fill=(255, 255, 255, 70))
                fx = (crop[0] + (crop[2] - crop[0]) * k / 10) if crop else k / 10
                fy = (crop[1] + (crop[3] - crop[1]) * k / 10) if crop else k / 10
                draw.text((x + 2, img.height - 16), f"{fx:.2f}", font=small, fill=(255, 255, 0, 220))
                draw.text((2, y + 1), f"{fy:.2f}", font=small, fill=(255, 255, 0, 220))
        draw.rectangle([0, 0, 170, 28], fill=(0, 0, 0, 190))
        draw.text((6, 3), f"{t:5.2f}s  f{index}", font=font, fill=(255, 255, 0))
        tiles.append(img)
    rows = (len(tiles) + cols - 1) // cols
    th = tiles[0].height
    canvas = Image.new("RGB", (cols * width, rows * th), (0, 0, 0))
    for i, tile in enumerate(tiles):
        canvas.paste(tile, ((i % cols) * width, (i // cols) * th))
    canvas.save(out, quality=88)
    return out


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("video")
    p.add_argument("out")
    p.add_argument("--start", type=float, default=0)
    p.add_argument("--end", type=float, default=3)
    p.add_argument("--fps", type=float, default=4)
    p.add_argument("--cols", type=int, default=3)
    p.add_argument("--width", type=int, default=640)
    p.add_argument("--grid", action="store_true")
    p.add_argument("--crop", type=float, nargs=4, default=None, help="x0 y0 x1 y1 normalized")
    a = p.parse_args()
    sheet(a.video, a.out, a.start, a.end, a.fps, a.cols, a.width, a.grid, a.crop)
