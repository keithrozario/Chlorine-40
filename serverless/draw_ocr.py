from PIL import Image, ImageDraw, ImageFont

txt = 'hello'
fontsize = 24
image = Image.new("RGBA", (400, 50), (255, 255, 255))
draw = ImageDraw.Draw(image)
font = ImageFont.truetype("fonts/DejaVuSans.ttf", fontsize)
draw.text((10, 0), txt, (0, 0, 0), font=font)
image.save("test.png")



