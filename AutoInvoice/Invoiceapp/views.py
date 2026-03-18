from django.shortcuts import render
from .ocr_utils import extract_text_from_file
from .llm_utils import convert_ocr_to_json
import json


def landing_page(request):
    return render(request, "index.html")


def home(request):
    context = {
        "selected_doc_type": "Invoice"
    }

    if request.method == "POST":
        uploaded_files = request.FILES.getlist("pdfFiles")
        doc_type = request.POST.get("doc_type", "Invoice").strip()

        context["selected_doc_type"] = doc_type

        if not uploaded_files:
            context["error"] = "Please upload at least one file."
            return render(request, "home.html", context)

        try:
            selected_files = []
            results = []

            for uploaded_file in uploaded_files:
                selected_files.append(uploaded_file.name)

                ocr_text = extract_text_from_file(uploaded_file)
                json_result = convert_ocr_to_json(ocr_text, uploaded_file.name)

                results.append(json_result)

            formatted_json = json.dumps(results, indent=4, ensure_ascii=False)

            context["selected_files"] = selected_files
            context["results"] = results
            context["formatted_json"] = formatted_json

        except Exception as e:
            context["error"] = f"Error during processing: {str(e)}"

    return render(request, "home.html", context)