#!/usr/bin/env python3
"""Normalize generated photo backgrounds to exact brand hexes so product
tiles blend seamlessly (corner-sampled bg -> target, feathered distance blend)."""
from PIL import Image
import os

def corner_color(img):
    w, h = img.size
    px = img.load()
    pts = [(3,3),(w-4,3),(3,h-4),(w-4,h-4),(3,h//2),(w-4,h//2)]
    rs = gs = bs = 0
    for x, y in pts:
        r, g, b = px[x, y][:3]; rs += r; gs += g; bs += b
    n = len(pts)
    return (rs//n, gs//n, bs//n)

def retint(src, dst, target, thresh=46):
    img = Image.open(src).convert("RGB")
    bg = corner_color(img)
    # skip if already close to target
    def dist(a, b): return max(abs(a[0]-b[0]), abs(a[1]-b[1]), abs(a[2]-b[2]))
    if dist(bg, target) <= 4:
        img.save(dst); print(f"{src} already ok"); return
    w, h = img.size
    px = img.load()
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y]
            d = max(abs(r-bg[0]), abs(g-bg[1]), abs(b-bg[2]))
            if d <= thresh:
                # feather: scale blend so edges stay smooth
                t = 1.0 - (d / thresh) * 0.5  # 0.5..1 blend strength
                nr = int(r + (target[0]-bg[0]) * t)
                ng = int(g + (target[1]-bg[1]) * t)
                nb = int(b + (target[2]-bg[2]) * t)
                px[x, y] = (max(0,min(255,nr)), max(0,min(255,ng)), max(0,min(255,nb)))
    img.save(dst)
    print(f"{src}: bg {bg} -> {target}")

TILE = (245, 246, 246)   # #F5F6F6
CREAM = (251, 240, 228)  # #FBF0E4

base = "assets/img"
for f in ["earbuds-ipx8","headphone-red","headphone-black","headphone-redwired",
          "headphone-anc","earbuds-tagry","bone-conduction","headphone-blue",
          "gaming-headset","laptop-pink"]:
    retint(f"{base}/{f}.png", f"{base}/{f}.png", TILE)

retint(f"{base}/headphone-red.png", f"{base}/hero-headphones.png", CREAM)
print("done")
