import os
import io
import numpy as np
import easyocr
import fitz
from PIL import Image

reader = easyocr.Reader(['en'], gpu=False)


def extract_from_image(image_input):
    result = reader.readtext(image_input, detail=0, paragraph=True)
    return "\n".join(result)


def extract_text_from_file(uploaded_file):
    file_name = uploaded_file.name
    ext = os.path.splitext(file_name)[1].lower()

    if ext in [".png", ".jpg", ".jpeg"]:
        image = Image.open(uploaded_file).convert("RGB")
        image_np = np.array(image)
        return extract_from_image(image_np)

    elif ext == ".pdf":
        pdf_bytes = uploaded_file.read()
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")

        all_text = []

        for page_number, page in enumerate(doc, start=1):
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            img_bytes = pix.tobytes("png")
            image = Image.open(io.BytesIO(img_bytes)).convert("RGB")
            image_np = np.array(image)

            page_text = extract_from_image(image_np)
            all_text.append(f"--- Page {page_number} ---\n{page_text}")

        doc.close()
        return "\n\n".join(all_text)

    else:
        return "Unsupported format"