"""Draws the Noise Remover app icon (1024px PNG). Usage: python make_icon.py out.png"""

import math
import random
import sys

from PIL import Image, ImageDraw, ImageFilter

S, SS = 1024, 4  # final size, supersampling factor
W = S * SS
PAD, RADIUS = 100 * SS, 185 * SS  # macOS icon grid: 824px body, rounded corners

img = Image.new("RGBA", (W, W), (0, 0, 0, 0))

# Drop shadow under the body.
shadow = Image.new("RGBA", (W, W), (0, 0, 0, 0))
ImageDraw.Draw(shadow).rounded_rectangle([PAD, PAD + 14 * SS, W - PAD, W - PAD + 14 * SS], RADIUS, fill=(0, 0, 0, 90))
img = Image.alpha_composite(img, shadow.filter(ImageFilter.GaussianBlur(18 * SS)))

# Indigo vertical gradient body (matches the web UI accent).
top, bot = (99, 91, 255), (67, 56, 202)
grad = Image.new("RGBA", (W, W))
gd = ImageDraw.Draw(grad)
for y in range(W):
    t = y / W
    gd.line([(0, y), (W, y)], fill=tuple(int(top[i] * (1 - t) + bot[i] * t) for i in range(3)) + (255,))
mask = Image.new("L", (W, W), 0)
ImageDraw.Draw(mask).rounded_rectangle([PAD, PAD, W - PAD, W - PAD], RADIUS, fill=255)
img.paste(grad, (0, 0), mask)

# Draw marks on their own layer so translucent fills blend instead of punching holes.
layer = Image.new("RGBA", (W, W), (0, 0, 0, 0))
d = ImageDraw.Draw(layer)

# Waveform: faint "noisy" bars on the left fading into bold clean speech bars.
cx = cy = W // 2
heights = [0.18, 0.32, 0.55, 0.38, 0.72, 0.95, 0.62, 0.85, 0.48, 0.66, 0.35, 0.24, 0.14]
bw, gap, maxh = 34 * SS, 22 * SS, 520 * SS
x0 = cx - (len(heights) * bw + (len(heights) - 1) * gap) // 2
for i, h in enumerate(heights):
    x, hh = x0 + i * (bw + gap), int(maxh * h)
    d.rounded_rectangle([x, cy - hh // 2, x + bw, cy + hh // 2], bw // 2, fill=(255, 255, 255, 120 if i < 4 else 255))

# Noise speckles around the faint bars.
random.seed(3)
for _ in range(26):
    x = random.randint(x0 - 20 * SS, x0 + 3 * (bw + gap) + bw + 20 * SS)
    y = cy + random.randint(-200 * SS, 200 * SS)
    r = random.randint(5, 9) * SS
    d.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 255, random.randint(50, 100)))


def sparkle(px, py, s):
    pts = [(px + (s if k % 2 == 0 else s * 0.28) * math.sin(k * math.pi / 4),
            py - (s if k % 2 == 0 else s * 0.28) * math.cos(k * math.pi / 4)) for k in range(8)]
    d.polygon(pts, fill=(255, 255, 255, 240))


sparkle(W - PAD - 130 * SS, PAD + 130 * SS, 64 * SS)
sparkle(W - PAD - 70 * SS, PAD + 245 * SS, 28 * SS)
img = Image.alpha_composite(img, layer)

img.resize((S, S), Image.LANCZOS).save(sys.argv[1])
