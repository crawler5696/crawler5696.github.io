#!/usr/bin/env python3
"""대시보드 아이콘 생성 (로컬 1회 실행용). 저장소에는 결과 PNG만 커밋된다."""
from PIL import Image, ImageDraw

S = 512
SS = 4  # supersampling
W = S * SS


def rounded_gradient(size, radius_ratio=0.24):
    w = h = size
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    # 세로 그라데이션 배경
    grad = Image.new("RGB", (1, h))
    top = (18, 33, 66)
    bot = (10, 16, 32)
    for y in range(h):
        t = y / (h - 1)
        grad.putpixel((0, y), tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)))
    grad = grad.resize((w, h))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=int(w * radius_ratio), fill=255)
    img.paste(grad, (0, 0), mask)
    return img, mask


def draw_chart(img, pad_ratio=0.20, glow=True):
    d = ImageDraw.Draw(img, "RGBA")
    pad = int(W * pad_ratio)
    left, right = pad, W - pad
    top, bottom = pad + int(W * 0.06), W - pad - int(W * 0.02)
    # 상승 라인 좌표
    pts = [
        (left, bottom - (bottom - top) * 0.16),
        (left + (right - left) * 0.22, bottom - (bottom - top) * 0.40),
        (left + (right - left) * 0.40, bottom - (bottom - top) * 0.30),
        (left + (right - left) * 0.62, bottom - (bottom - top) * 0.60),
        (left + (right - left) * 0.80, bottom - (bottom - top) * 0.52),
        (right, bottom - (bottom - top) * 0.90),
    ]
    # 영역 채우기
    area = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    da = ImageDraw.Draw(area)
    da.polygon(pts + [(right, bottom + int(W * 0.02)), (left, bottom + int(W * 0.02))], fill=(79, 140, 255, 70))
    img.alpha_composite(area)

    if glow:
        g = Image.new("RGBA", (W, W), (0, 0, 0, 0))
        dg = ImageDraw.Draw(g)
        dg.line(pts, fill=(120, 170, 255, 90), width=int(W * 0.075), joint="curve")
        img.alpha_composite(g.filter(__import__("PIL.ImageFilter", fromlist=["ImageFilter"]).GaussianBlur(W * 0.018)))

    d.line(pts, fill=(160, 195, 255, 255), width=int(W * 0.032), joint="curve")
    # 마지막 점
    x, y = pts[-1]
    r = W * 0.035
    d.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 255, 255))
    # 마지막 점 주변 잔광
    if glow:
        halo = Image.new("RGBA", (W, W), (0, 0, 0, 0))
        dh = ImageDraw.Draw(halo)
        rh = W * 0.085
        dh.ellipse([x - rh, y - rh, x + rh, y + rh], fill=(220, 235, 255, 90))
        from PIL import ImageFilter
        img.alpha_composite(halo.filter(ImageFilter.GaussianBlur(W * 0.02)))


def make(radius_ratio, pad_ratio, path):
    img, _mask = rounded_gradient(W, radius_ratio)
    draw_chart(img, pad_ratio)
    img = img.resize((S, S), Image.LANCZOS)
    img.save(path)
    print("saved", path)


make(0.24, 0.20, "icons/icon-512.png")
make(0.24, 0.20, "icons/icon-192.png")
make(0.24, 0.30, "icons/icon-maskable-512.png")

# 192 사이즈도 만든다
img = Image.open("icons/icon-512.png").resize((192, 192), Image.LANCZOS)
img.save("icons/icon-192.png")
print("saved icons/icon-192.png")
