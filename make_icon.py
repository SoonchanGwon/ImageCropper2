"""앱 아이콘(icon.ico) 생성"""
from PIL import Image, ImageDraw

S = 256
im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(im)
d.rounded_rectangle((8, 8, S - 8, S - 8), radius=56, fill=(91, 140, 255))
d.rounded_rectangle((60, 70, 196, 186), radius=10, fill=(255, 255, 255, 70))
w = 16
# 자르기 표시(ㄱ자 두 개)
d.line([(78, 40), (78, 178), (216, 178)], fill="white", width=w, joint="curve")
d.line([(40, 78), (178, 78), (178, 216)], fill="white", width=w, joint="curve")
im.save(__file__.replace("make_icon.py", "icon.ico"),
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
