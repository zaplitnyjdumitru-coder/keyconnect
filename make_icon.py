"""Рисует иконку KeyConnect: щит с замочной скважиной на синем градиенте."""
from PIL import Image, ImageDraw

S = 1024
TOP, BOTTOM = (37, 99, 235), (14, 165, 233)

grad = Image.new("RGBA", (S, S))
gd = ImageDraw.Draw(grad)
for y in range(S):
    t = y / (S - 1)
    gd.line([(0, y), (S, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(TOP, BOTTOM)))

mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle([40, 40, S - 40, S - 40], radius=230, fill=255)
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
img.paste(grad, (0, 0), mask)

d = ImageDraw.Draw(img)
d.polygon([(512, 190), (790, 290), (775, 560), (700, 700), (512, 840),
           (324, 700), (249, 560), (234, 290)], fill="white")
hole = (30, 110, 235)
d.ellipse([447, 370, 577, 500], fill=hole)
d.polygon([(482, 470), (542, 470), (566, 660), (458, 660)], fill=hole)

img.save("icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
img.save("icon.icns")
img.resize((256, 256), Image.LANCZOS).save("icon.png")
print("icon.ico, icon.icns, icon.png готовы")
