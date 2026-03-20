from django.shortcuts import render
from .ocr_utils import extract_text_from_file
from .llm_utils import convert_ocr_to_json
import json


def landing_page(request):
    return render(request, "index.html")


def to_float(value, default=0.0):
    """
    Convert value to float safely.
    Removes commas and currency symbols where possible.
    """
    if value is None or value == "":
        return default

    if isinstance(value, (int, float)):
        return float(value)

    try:
        cleaned = str(value).strip().replace(",", "")
        cleaned = cleaned.replace("₹", "").replace("$", "").replace("AED", "").replace("INR", "")
        return float(cleaned)
    except Exception:
        return default


def to_int(value, default=0):
    """
    Convert value to int safely.
    """
    if value is None or value == "":
        return default

    if isinstance(value, int):
        return value

    try:
        return int(float(str(value).strip().replace(",", "")))
    except Exception:
        return default


def to_bool(value, default=False):
    """
    Convert value to bool safely.
    """
    if isinstance(value, bool):
        return value

    if value is None or value == "":
        return default

    value_str = str(value).strip().lower()

    if value_str in ["true", "1", "yes", "y"]:
        return True
    if value_str in ["false", "0", "no", "n"]:
        return False

    return default


def clean_line_items(line_items):
    """
    Convert extracted line_items into Zoho-friendly structure.
    Keeps only meaningful rows.
    """
    cleaned_items = []

    if not isinstance(line_items, list):
        return cleaned_items

    for index, item in enumerate(line_items, start=1):
        if not isinstance(item, dict):
            continue

        cleaned_item = {
            "purchaseorder_item_id": str(item.get("purchaseorder_item_id", "") or ""),
            "line_item_id": str(item.get("line_item_id", "") or ""),
            "item_id": str(item.get("item_id", "") or ""),
            "name": str(item.get("name", "") or ""),
            "account_id": str(item.get("account_id", "") or ""),
            "description": str(item.get("description", "") or ""),
            "rate": to_float(item.get("rate")),
            "hsn_or_sac": to_int(item.get("hsn_or_sac")),
            "reverse_charge_tax_id": to_int(item.get("reverse_charge_tax_id")),
            "location_id": str(item.get("location_id", "") or ""),
            "quantity": to_float(item.get("quantity")),
            "tax_id": str(item.get("tax_id", "") or ""),
            "tds_tax_id": str(item.get("tds_tax_id", "") or ""),
            "tax_treatment_code": str(item.get("tax_treatment_code", "") or ""),
            "tax_exemption_id": str(item.get("tax_exemption_id", "") or ""),
            "tax_exemption_code": str(item.get("tax_exemption_code", "") or ""),
            "item_order": to_int(item.get("item_order"), index),
            "product_type": str(item.get("product_type", "") or ""),
            "acquisition_vat_id": str(item.get("acquisition_vat_id", "") or ""),
            "reverse_charge_vat_id": str(item.get("reverse_charge_vat_id", "") or ""),
            "unit": str(item.get("unit", "") or ""),
            "tags": item.get("tags", []) if isinstance(item.get("tags"), list) else [],
            "is_billable": to_bool(item.get("is_billable")),
            "project_id": str(item.get("project_id", "") or ""),
            "customer_id": str(item.get("customer_id", "") or ""),
            "item_custom_fields": item.get("item_custom_fields", []) if isinstance(item.get("item_custom_fields"), list) else [],
            "serial_numbers": item.get("serial_numbers", []) if isinstance(item.get("serial_numbers"), list) else [],
        }

        # skip fully empty item rows
        has_meaningful_data = any([
            cleaned_item["name"],
            cleaned_item["description"],
            cleaned_item["rate"] != 0,
            cleaned_item["quantity"] != 0,
            cleaned_item["item_id"],
        ])

        if has_meaningful_data:
            cleaned_items.append(cleaned_item)

    return cleaned_items


def clean_taxes(taxes):
    """
    Convert extracted taxes into Zoho-friendly structure.
    """
    cleaned_taxes = []

    if not isinstance(taxes, list):
        return cleaned_taxes

    for tax in taxes:
        if not isinstance(tax, dict):
            continue

        cleaned_tax = {
            "tax_id": str(tax.get("tax_id", "") or ""),
            "tax_name": str(tax.get("tax_name", "") or ""),
            "tax_amount": to_float(tax.get("tax_amount")),
        }

        has_meaningful_data = any([
            cleaned_tax["tax_id"],
            cleaned_tax["tax_name"],
            cleaned_tax["tax_amount"] != 0,
        ])

        if has_meaningful_data:
            cleaned_taxes.append(cleaned_tax)

    return cleaned_taxes


def prepare_zoho_bill_payload(extracted_data, source_file_name=""):
    """
    Convert LLM extracted JSON into a Zoho Books Bills payload-friendly structure.
    """
    if not isinstance(extracted_data, dict):
        extracted_data = {}

    documents = extracted_data.get("documents", [])
    if not isinstance(documents, list):
        documents = []

    if not documents:
        documents = [
            {
                "document_id": 0,
                "file_name": source_file_name
            }
        ]

    payload = {
        "vendor_id": str(extracted_data.get("vendor_id", "") or ""),
        "currency_id": str(extracted_data.get("currency_id", "") or ""),
        "vat_treatment": str(extracted_data.get("vat_treatment", "") or ""),
        "is_update_customer": to_bool(extracted_data.get("is_update_customer")),
        "purchaseorder_ids": extracted_data.get("purchaseorder_ids", []) if isinstance(extracted_data.get("purchaseorder_ids"), list) else [],
        "bill_number": str(extracted_data.get("bill_number", "") or ""),
        "documents": documents,
        "source_of_supply": str(extracted_data.get("source_of_supply", "") or ""),
        "destination_of_supply": str(extracted_data.get("destination_of_supply", "") or ""),
        "place_of_supply": str(extracted_data.get("place_of_supply", "") or ""),
        "permit_number": str(extracted_data.get("permit_number", "") or ""),
        "gst_treatment": str(extracted_data.get("gst_treatment", "") or ""),
        "tax_treatment": str(extracted_data.get("tax_treatment", "") or ""),
        "gst_no": str(extracted_data.get("gst_no", "") or ""),
        "pricebook_id": to_int(extracted_data.get("pricebook_id")),
        "reference_number": str(extracted_data.get("reference_number", "") or ""),
        "date": str(extracted_data.get("date", "") or ""),
        "due_date": str(extracted_data.get("due_date", "") or ""),
        "payment_terms": to_int(extracted_data.get("payment_terms")),
        "payment_terms_label": str(extracted_data.get("payment_terms_label", "") or ""),
        "recurring_bill_id": str(extracted_data.get("recurring_bill_id", "") or ""),
        "exchange_rate": to_float(extracted_data.get("exchange_rate"), 0),
        "is_item_level_tax_calc": to_bool(extracted_data.get("is_item_level_tax_calc")),
        "is_inclusive_tax": to_bool(extracted_data.get("is_inclusive_tax")),
        "adjustment": to_float(extracted_data.get("adjustment"), 0),
        "adjustment_description": str(extracted_data.get("adjustment_description", "") or ""),
        "location_id": str(extracted_data.get("location_id", "") or ""),
        "custom_fields": extracted_data.get("custom_fields", []) if isinstance(extracted_data.get("custom_fields"), list) else [],
        "tags": extracted_data.get("tags", []) if isinstance(extracted_data.get("tags"), list) else [],
        "line_items": clean_line_items(extracted_data.get("line_items", [])),
        "taxes": clean_taxes(extracted_data.get("taxes", [])),
        "notes": str(extracted_data.get("notes", "") or ""),
        "terms": str(extracted_data.get("terms", "") or ""),
        "approvers": extracted_data.get("approvers", []) if isinstance(extracted_data.get("approvers"), list) else [],
        "unmapped_fields": extracted_data.get("unmapped_fields", {}) if isinstance(extracted_data.get("unmapped_fields"), dict) else {},
    }

    return payload
# performance measurement check code

import time

def measure_time(label, func, *args, **kwargs):
    start_time = time.time()
    result = func(*args, **kwargs)
    end_time = time.time()

    print(f"{label} took {end_time - start_time:.2f} sec")

    return result

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
            raw_results = []
            zoho_payloads = []

            for uploaded_file in uploaded_files:
                selected_files.append(uploaded_file.name)

                # Step 1: OCR extract
                ocr_text = extract_text_from_file(uploaded_file)

                # Step 2: LLM structured extraction
                extracted_json = convert_ocr_to_json(ocr_text, uploaded_file.name)
                raw_results.append(extracted_json)

                # Step 3: Clean for Zoho Books Bill API usage
                zoho_payload = prepare_zoho_bill_payload(extracted_json, uploaded_file.name)
                zoho_payloads.append(zoho_payload)

            context["selected_files"] = selected_files
            context["results"] = raw_results
            context["formatted_json"] = json.dumps(raw_results, indent=4, ensure_ascii=False)

            # this is the cleaned payload you can use for Zoho Books bills API
            context["zoho_payloads"] = zoho_payloads
            context["formatted_zoho_json"] = json.dumps(zoho_payloads, indent=4, ensure_ascii=False)

        except Exception as e:
            context["error"] = f"Error during processing: {str(e)}"

    return render(request, "home.html", context)