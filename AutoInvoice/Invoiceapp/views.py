from django.shortcuts import render
from .ocr_utils import extract_text_from_file
from .llm_utils import convert_ocr_to_json
import json


def landing_page(request):
    return render(request, "index.html")


def home(request):
    if request.method == "POST":
        batch_name = request.POST.get("batch_name", "").strip()
        uploaded_files = request.FILES.getlist("pdfFiles")

        if not batch_name:
            return render(request, "home.html", {
                "error": "Batch Name is required."
            })

        if not uploaded_files:
            return render(request, "home.html", {
                "error": "Please upload at least one file."
            })

        try:
            selected_files = []
            results = []

            for uploaded_file in uploaded_files:
                selected_files.append(uploaded_file.name)

                ocr_text = extract_text_from_file(uploaded_file)
                json_result = convert_ocr_to_json(ocr_text, uploaded_file.name)

                # THIS LINE IS THE IMPORTANT FIX
                formatted_json = json.dumps(json_result, indent=4, ensure_ascii=False)

                results.append({
                    "file_name": uploaded_file.name,
                    "json_result": formatted_json
                })

            return render(request, "home.html", {
                "batch_name_value": batch_name,
                "selected_files": selected_files,
                "results": results
            })

        except Exception as e:
            return render(request, "home.html", {
                "error": f"Error during processing: {str(e)}"
            })

    return render(request, "home.html")