#!/usr/bin/env python3
"""Generate clean flat-illustration placeholder product art on the site's
product-tile background color (#F5F6F6) so tiles stay cohesive until the
AI photo versions are generated next turn."""
from PIL import Image, ImageDraw, ImageFilter

BG = (245, 246, 246)
SIZE = 640

def canvas():
    return Image.new("RGB", (SIZE, SIZE), BG)

def soft_shadow(img, box, blur=14, alpha=40):
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(sh)
    d.ellipse(box, fill=(0, 0, 0, alpha))
    sh = sh.filter(ImageFilter.GaussianBlur(blur))
    img.paste(Image.alpha_composite(img.convert("RGBA"), sh).convert("RGB"), (0, 0))

def homepod():
    img = canvas(); d = ImageDraw.Draw(img)
    soft_shadow(img, (170, 470, 470, 545))
    # body sphere
    d.ellipse([150, 130, 490, 470], fill=(226, 111, 66))
    # mesh shading rings
    for r, col in [(315, (226, 111, 66)), (270, (232, 124, 80)), (225, (238, 139, 96)), (180, (242, 155, 114)), (135, (246, 173, 136))]:
        d.ellipse([320 - r, 300 - r, 320 + r, 300 + r], fill=col)
    # fabric mesh dots
    for i in range(-12, 13):
        for j in range(-12, 13):
            x = 320 + i * 13 + (6 if j % 2 else 0); y = 300 + j * 13
            if (x - 320) ** 2 + (y - 300) ** 2 < 150 ** 2:
                d.ellipse([x - 2, y - 2, x + 2, y + 2], fill=(214, 100, 56))
    # top touch panel
    d.rounded_rectangle([250, 118, 390, 158], 20, fill=(246, 214, 200))
    d.rounded_rectangle([270, 128, 370, 148], 10, fill=(252, 231, 220))
    img.save("assets/img/homepod-orange.png")

def sleeve():
    img = canvas(); d = ImageDraw.Draw(img)
    soft_shadow(img, (150, 470, 500, 540))
    # sleeve body
    d.rounded_rectangle([140, 190, 500, 490], 26, fill=(232, 176, 75))
    # front pocket
    d.rounded_rectangle([140, 300, 500, 490], 26, fill=(240, 186, 88))
    d.line([160, 300, 480, 300], fill=(206, 152, 60), width=4)
    # flap + zip on top edge
    d.rounded_rectangle([150, 178, 490, 210], 14, fill=(214, 158, 62))
    d.line([165, 194, 475, 194], fill=(176, 126, 44), width=3)
    # phone sticking out of pocket
    d.rounded_rectangle([350, 240, 430, 356], 12, fill=(250, 250, 250))
    d.rounded_rectangle([358, 248, 422, 344], 8, fill=(206, 217, 228))
    d.rounded_rectangle([376, 240, 404, 248], 4, fill=(225, 225, 225))
    # notebook
    d.rounded_rectangle([170, 318, 300, 452], 8, fill=(248, 246, 240))
    d.rounded_rectangle([170, 318, 300, 452], 8, outline=(222, 218, 208), width=3)
    d.line([186, 344, 284, 344], fill=(205, 200, 190), width=3)
    d.line([186, 366, 284, 366], fill=(205, 200, 190), width=3)
    img.save("assets/img/sleeve-yellow.png")

def sofa():
    img = canvas(); d = ImageDraw.Draw(img)
    soft_shadow(img, (150, 460, 500, 530))
    # legs
    for x0, x1 in [(168, 186), (444, 462)]:
        d.polygon([(x0, 420), (x1, 420), (x1 - 2, 490), (x0 + 2, 490)], fill=(164, 116, 74))
    # backrest
    d.rounded_rectangle([160, 160, 340, 300], 22, fill=(96, 99, 110))
    # arms
    d.rounded_rectangle([150, 250, 200, 440], 18, fill=(88, 91, 102))
    d.rounded_rectangle([440, 250, 490, 440], 18, fill=(88, 91, 102))
    # seat base
    d.rounded_rectangle([160, 350, 480, 450], 24, fill=(80, 83, 94))
    # seat cushion
    d.rounded_rectangle([190, 330, 450, 400], 18, fill=(106, 109, 122))
    img.save("assets/img/cat-sofa.png")

def shoe():
    img = canvas(); d = ImageDraw.Draw(img)
    soft_shadow(img, (130, 420, 510, 480))
    # sole
    d.rounded_rectangle([120, 390, 520, 440], 25, fill=(232, 229, 220))
    d.rounded_rectangle([120, 404, 520, 445], 22, fill=(208, 196, 178))
    # upper base
    d.polygon([(130, 396), (150, 320), (210, 260), (300, 232), (360, 250), (430, 300), (490, 330), (515, 360), (518, 396)],
              fill=(248, 247, 243))
    # heel counter (orange)
    d.polygon([(130, 396), (150, 320), (200, 275), (215, 396)], fill=(239, 148, 74))
    # teal mid panel
    d.polygon([(215, 396), (228, 320), (300, 290), (348, 396)], fill=(122, 199, 192))
    # toe box overlay
    d.polygon([(360, 396), (400, 320), (470, 330), (515, 365), (518, 396)], fill=(240, 238, 232))
    # laces
    for i in range(4):
        y = 268 + i * 26
        d.line([(268 - i * 6, y), (330 - i * 2, y + 16)], fill=(255, 255, 255), width=9)
    # collar
    d.rounded_rectangle([250, 225, 350, 265], 16, fill=(252, 252, 250))
    img.save("assets/img/cat-shoe.png")

def bag():
    img = canvas(); d = ImageDraw.Draw(img)
    soft_shadow(img, (140, 440, 500, 500))
    # handles
    d.arc([240, 150, 330, 260], 180, 360, fill=(226, 138, 158), width=16)
    d.arc([300, 150, 390, 260], 180, 360, fill=(226, 138, 158), width=16)
    # body
    d.rounded_rectangle([140, 240, 500, 450], 40, fill=(241, 166, 184))
    # quilt lines
    for x in range(180, 500, 44):
        d.line([(x, 246), (x - 10, 446)], fill=(231, 148, 168), width=4)
    # zipper
    d.rounded_rectangle([170, 246, 470, 262], 8, fill=(214, 216, 142 if False else 130))
    d.rounded_rectangle([176, 249, 464, 259], 5, fill=(236, 204, 154))
    img.save("assets/img/cat-bag.png")

def book():
    img = canvas(); d = ImageDraw.Draw(img)
    soft_shadow(img, (210, 500, 440, 540))
    # pages
    d.polygon([(400, 150), (424, 162), (424, 502), (400, 490)], fill=(250, 248, 242))
    for y in range(170, 495, 12):
        d.line([(404, y), (420, y + 8)], fill=(222, 218, 208), width=2)
    # cover (front)
    d.rounded_rectangle([216, 150, 400, 490], 6, fill=(244, 183, 63))
    # spine
    d.polygon([(216, 150), (400, 150), (400, 490), (216, 490)], fill=(246, 190, 74))
    d.polygon([(216, 150), (232, 150), (232, 490), (216, 490)], fill=(214, 158, 48))
    # decorative shapes (no text)
    d.ellipse([258, 210, 358, 310], fill=(250, 226, 160))
    d.rectangle([258, 350, 358, 368], fill=(233, 160, 44))
    d.rectangle([258, 384, 330, 398], fill=(233, 160, 44))
    img.save("assets/img/cat-book.png")

def headphones_variant(fname, band, cup, cushion):
    img = canvas(); d = ImageDraw.Draw(img)
    soft_shadow(img, (200, 470, 440, 525))
    # headband (arc as thick line)
    d.arc([150, 100, 490, 500], 195, 345, fill=band, width=34)
    d.arc([170, 122, 470, 492], 195, 345, fill=tuple(max(c - 16, 0) for c in band), width=12)
    # left cup + right cup
    for cx in (196, 444):
        d.rounded_rectangle([cx - 38, 330, cx + 38, 470], 26, fill=cup)
        d.rounded_rectangle([cx - 38 + (8 if cx < 300 else -16), 344, cx - 22 + (8 if cx < 300 else -16), 456], 12, fill=cushion)
        d.ellipse([cx - 20, 368, cx + 20, 432], fill=tuple(min(c + 18, 255) for c in cup))
    img.save(f"assets/img/{fname}.png")

homepod(); sleeve(); sofa(); shoe(); bag(); book()
headphones_variant("headphone-green", (168, 196, 176), (146, 176, 156), (210, 228, 214))
headphones_variant("headphone-silver", (208, 210, 214), (232, 233, 236), (200, 202, 206))
print("placeholders done")
