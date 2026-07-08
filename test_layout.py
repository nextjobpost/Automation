import os
import sys
# Set fallback font path to make sure it runs on Windows
os.environ["FONT_PATH"] = "C:\\Windows\\Fonts\\arial.ttf"

from bot1 import generate_poster

try:
    print("Generating test poster...")
    generate_poster(
        title="DevOps Engineer",
        company="STATUSNEO",
        location="Remote",
        salary="Best in Industry",
        output_path="test_layout.jpg",
        is_govt=False,
        vacancies="5",
        last_date="2026-07-15"
    )
    print("✅ Test poster generated successfully as test_layout.jpg!")
except Exception as e:
    print(f"❌ Error: {e}")
