import os
from bot1 import generate_poster

output_path = "test_output.png"
if os.path.exists(output_path):
    os.remove(output_path)

try:
    generate_poster(
        title="Student Internship Scheme",
        company="NABARD",
        location="Pan India",
        salary="Not Mentioned",
        output_path=output_path
    )
    if os.path.exists(output_path):
        print(f"SUCCESS! Poster generated at {output_path}")
    else:
        print("FAILED: File was not created.")
except Exception as e:
    print(f"FAILED with exception: {e}")
