import os
import urllib.request
from PIL import Image, ImageDraw, ImageFont

# Define path
ARTIFACTS_DIR = "/home/ujjawal-singh/.gemini/antigravity/brain/c341abd3-f20b-4aeb-8931-a663fcb0a4e8/artifacts"
output_path = os.path.join(ARTIFACTS_DIR, "sample_poster.jpg")

FONT_DIR = "assets/fonts"
FONT_PATH = os.path.join(FONT_DIR, "Roboto-Bold.ttf")

if not os.path.exists(FONT_DIR):
    os.makedirs(FONT_DIR)

if not os.path.exists(FONT_PATH):
    url = "https://raw.githubusercontent.com/googlefonts/roboto/master/src/hinted/Roboto-Bold.ttf"
    urllib.request.urlretrieve(url, FONT_PATH)

def wrap_text(text, font, max_width):
    lines = []
    paragraphs = text.split('\n')
    for p in paragraphs:
        if not p:
            continue
        words = p.split()
        current_line = []
        for word in words:
            test_line = " ".join(current_line + [word])
            wbox = font.getbbox(test_line)
            w = wbox[2] - wbox[0]
            if w <= max_width:
                current_line.append(word)
            else:
                lines.append(" ".join(current_line))
                current_line = [word]
        if current_line:
            lines.append(" ".join(current_line))
    return lines

def generate_poster(title, company, location, salary, output_path):
    width, height = 1200, 630
    
    # 1. Create a dark blue background
    base_grad = Image.new("RGB", (2, 2))
    base_grad.putpixel((0, 0), (14, 25, 45))  # Dark Blue
    base_grad.putpixel((1, 0), (20, 35, 60))  
    base_grad.putpixel((0, 1), (10, 20, 40))  
    base_grad.putpixel((1, 1), (15, 28, 50))  
    
    img = base_grad.resize((width, height), Image.Resampling.BILINEAR)
    draw = ImageDraw.Draw(img)
    
    # Load fonts
    try:
        font_company = ImageFont.truetype(FONT_PATH, 28)
        font_title = ImageFont.truetype(FONT_PATH, 64)
        font_meta = ImageFont.truetype(FONT_PATH, 32)
        font_footer = ImageFont.truetype(FONT_PATH, 24)
    except Exception as e:
        print(f"Error loading font: {e}")
        font_company = font_title = font_meta = font_footer = ImageFont.load_default()
        
    orange_color = (245, 158, 11) # Amber 500
    white_color = (255, 255, 255)
    light_gray = (209, 213, 219)
    
    def get_text_width(text, font):
        return font.getbbox(text)[2] - font.getbbox(text)[0]
        
    # Top Line
    line_width = 400
    line_x0 = (width - line_width) // 2
    draw.line([(line_x0, 120), (line_x0 + line_width, 120)], fill=orange_color, width=3)
    
    # Company Name
    company_text = company.upper()
    cw = get_text_width(company_text, font_company)
    draw.text(((width - cw) // 2, 140), company_text, fill=white_color, font=font_company)
    
    # Job Title (with wrapping)
    wrapped_title = wrap_text(title, font_title, 1000)
    y_offset = 220
    for line in wrapped_title:
        lw = get_text_width(line, font_title)
        draw.text(((width - lw) // 2, y_offset), line, fill=white_color, font=font_title)
        y_offset += 80
        
    # Meta details (Location/Salary)
    y_offset += 20
    meta_text = []
    if location and location.lower() != "not mentioned":
        meta_text.append(f"{location}")
    if salary and salary.lower() != "not mentioned":
        meta_text.append(f"{salary}")
        
    if meta_text:
        meta_str = " | ".join(meta_text)
        mw = get_text_width(meta_str, font_meta)
        draw.text(((width - mw) // 2, y_offset), meta_str, fill=orange_color, font=font_meta)
        y_offset += 60
        
    # Bottom Line
    draw.line([(line_x0, y_offset + 30), (line_x0 + line_width, y_offset + 30)], fill=orange_color, width=3)
    
    # Footer
    footer_text = "nextjobpost.in"
    fw = get_text_width(footer_text, font_footer)
    draw.text(((width - fw) // 2, y_offset + 60), footer_text, fill=light_gray, font=font_footer)
    
    # Save Image
    img.save(output_path, "JPEG", quality=85, optimize=True)
    print(f"Image saved to {output_path}")

generate_poster(
    title="Student Internship Scheme 2026-27",
    company="NABARD",
    location="Pan India",
    salary="Recruitment 2026",
    output_path=output_path
)
