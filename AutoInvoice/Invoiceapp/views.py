from django.shortcuts import render
from .ocr_utils import extract_text_from_file
from .llm_utils import convert_ocr_to_json
import json
import urllib.parse
import urllib.request
import urllib.error
import os
from datetime import datetime
from dotenv import load_dotenv
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

load_dotenv()

DEFAULT_BILL_ACCOUNT_ID = os.getenv("DEFAULT_BILL_ACCOUNT_ID", "").strip()
COMPANY_GST_STATE_CODE = os.getenv("COMPANY_GST_STATE_CODE", "").strip()


def landing_page(request):
    return render(request, "index.html")


def to_float(value, default=0.0):
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
    if value is None or value == "":
        return default
    if isinstance(value, int):
        return value
    try:
        return int(float(str(value).strip().replace(",", "")))
    except Exception:
        return default


def clean_empty_values(data):
    """
    Remove empty string / None / empty list / empty dict values.
    Keep False, 0, 0.0 because they are valid values.
    """
    if isinstance(data, dict):
        cleaned = {}
        for key, value in data.items():
            cleaned_value = clean_empty_values(value)
            if cleaned_value in [None, "", [], {}]:
                continue
            cleaned[key] = cleaned_value
        return cleaned

    if isinstance(data, list):
        cleaned_list = []
        for item in data:
            cleaned_item = clean_empty_values(item)
            if cleaned_item in [None, "", [], {}]:
                continue
            cleaned_list.append(cleaned_item)
        return cleaned_list

    return data


def parse_llm_json(raw_data):
    """
    convert_ocr_to_json may return:
    - dict
    - list
    - JSON string
    - JSON string wrapped with extra text
    """
    if isinstance(raw_data, (dict, list)):
        return raw_data

    if isinstance(raw_data, str):
        raw_data = raw_data.strip()
        if not raw_data:
            raise Exception("LLM returned empty response")

        try:
            return json.loads(raw_data)
        except json.JSONDecodeError:
            start_obj = raw_data.find("{")
            end_obj = raw_data.rfind("}")
            if start_obj != -1 and end_obj != -1 and end_obj > start_obj:
                try:
                    return json.loads(raw_data[start_obj:end_obj + 1])
                except Exception:
                    pass

            start_arr = raw_data.find("[")
            end_arr = raw_data.rfind("]")
            if start_arr != -1 and end_arr != -1 and end_arr > start_arr:
                try:
                    return json.loads(raw_data[start_arr:end_arr + 1])
                except Exception:
                    pass

        raise Exception("LLM response is not valid JSON")

    raise Exception("Unsupported LLM response format")


def normalize_zoho_date(date_value):
    """
    Convert OCR/LLM extracted dates into YYYY-MM-DD format for Zoho.
    Supports:
    - 20/02/26
    - 20/02/2026
    - 20-02-2026
    - 2026-02-20
    - 20.02.2026
    """
    if not date_value:
        return ""

    raw = str(date_value).strip()

    formats_to_try = [
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d/%m/%y",
        "%d-%m-%Y",
        "%d-%m-%y",
        "%d.%m.%Y",
        "%d.%m.%y",
        "%m/%d/%Y",
        "%m/%d/%y",
    ]

    for fmt in formats_to_try:
        try:
            parsed = datetime.strptime(raw, fmt)
            return parsed.strftime("%Y-%m-%d")
        except Exception:
            continue

    raise Exception(f"Invalid date format from OCR/LLM: {raw}")


def get_access_token(accounts_base_url, client_id, client_secret, refresh_token):
    token_url = f"{accounts_base_url}/oauth/v2/token"

    post_data = urllib.parse.urlencode({
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "refresh_token"
    }).encode("utf-8")

    req = urllib.request.Request(token_url, data=post_data, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            response_data = response.read().decode("utf-8")
            token_json = json.loads(response_data)
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        try:
            token_json = json.loads(error_body)
        except Exception:
            token_json = {"error": error_body}
        raise Exception(token_json.get("error", "Failed to generate access token"))

    access_token = token_json.get("access_token")
    if not access_token:
        raise Exception(token_json.get("error", "Failed to generate access token"))

    return access_token


def make_zoho_request(url, method="GET", access_token="", body=None):
    headers = {
        "Authorization": f"Zoho-oauthtoken {access_token}"
    }

    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")

    req = urllib.request.Request(url, data=data, method=method)
    for key, value in headers.items():
        req.add_header(key, value)

    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            response_data = response.read().decode("utf-8")
            return json.loads(response_data)
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        try:
            return json.loads(error_body)
        except Exception:
            return {"message": error_body, "code": e.code}
    except Exception as e:
        return {"message": str(e), "code": -1}


def get_state_code_from_gst(gst_no):
    """
    GST first 2 digits = state code
    Example: 33ABCDE1234F1ZS -> 33
    """
    if not gst_no:
        return ""
    gst_no = str(gst_no).strip()
    if len(gst_no) >= 2 and gst_no[:2].isdigit():
        return gst_no[:2]
    return ""


def detect_transaction_type(vendor_gst_no):
    """
    Returns:
    - intra
    - inter
    - unknown
    """
    vendor_state_code = get_state_code_from_gst(vendor_gst_no)
    company_state_code = str(COMPANY_GST_STATE_CODE or "").strip()

    if not vendor_state_code or not company_state_code:
        return "unknown"

    if vendor_state_code == company_state_code:
        return "intra"

    return "inter"


def fetch_tax_details(api_base_url, organization_id, access_token):
    url = f"{api_base_url}/books/v3/settings/taxes?organization_id={organization_id}"
    response_json = make_zoho_request(
        url=url,
        method="GET",
        access_token=access_token
    )

    if response_json.get("code") not in [0, "0"]:
        raise Exception(response_json.get("message", "Failed to fetch tax details"))

    taxes = response_json.get("taxes", [])
    if not isinstance(taxes, list):
        return []

    return taxes


def find_matching_tax_ids(taxes, tax_percentage, transaction_type):
    """
    Dynamic tax selection:
    intra -> use tax_group GST5/GST12/GST18/GST28
    inter -> use IGST5/IGST12/IGST18/IGST28

    Returns line_item_taxes format:
    [{"tax_id": "..."}]
    """
    target_percentage = round(to_float(tax_percentage, 0), 2)

    if target_percentage <= 0:
        return []

    # intra state: pick tax_group with matching percentage and tax_specification=intra
    if transaction_type == "intra":
        for tax in taxes:
            if not isinstance(tax, dict):
                continue

            tax_id = str(tax.get("tax_id", "") or "").strip()
            tax_type = str(tax.get("tax_type", "") or "").strip().lower()
            tax_specification = str(tax.get("tax_specification", "") or "").strip().lower()
            tax_percentage_value = round(to_float(tax.get("tax_percentage"), 0), 2)
            is_inactive = bool(tax.get("is_inactive", False))

            if is_inactive:
                continue

            if (
                tax_id
                and tax_type == "tax_group"
                and tax_specification == "intra"
                and tax_percentage_value == target_percentage
            ):
                return [{"tax_id": tax_id}]

    # inter state: pick IGST tax with matching percentage and tax_specification=inter
    if transaction_type == "inter":
        for tax in taxes:
            if not isinstance(tax, dict):
                continue

            tax_id = str(tax.get("tax_id", "") or "").strip()
            tax_name = str(tax.get("tax_name", "") or "").strip().upper()
            tax_type = str(tax.get("tax_type", "") or "").strip().lower()
            tax_specific_type = str(tax.get("tax_specific_type", "") or "").strip().lower()
            tax_specification = str(tax.get("tax_specification", "") or "").strip().lower()
            tax_percentage_value = round(to_float(tax.get("tax_percentage"), 0), 2)
            is_inactive = bool(tax.get("is_inactive", False))

            if is_inactive:
                continue

            if (
                tax_id
                and tax_type == "tax"
                and tax_specific_type == "igst"
                and tax_specification == "inter"
                and tax_percentage_value == target_percentage
                and tax_name.startswith("IGST")
            ):
                return [{"tax_id": tax_id}]

    return []


def prepare_vendor_payload(extracted_data):
    if not isinstance(extracted_data, dict):
        extracted_data = {}

    vendor_details = extracted_data.get("vendor_details", {})
    if not isinstance(vendor_details, dict):
        vendor_details = {}

    payload = {
        "contact_name": str(vendor_details.get("name", "") or vendor_details.get("company_name", "") or "").strip(),
        "company_name": str(vendor_details.get("company_name", "") or vendor_details.get("name", "") or "").strip(),
        "contact_type": "vendor",
        "contact_type_form": "company",
        "language_code": str(vendor_details.get("language_code", "") or "en").strip(),
        "website": str(vendor_details.get("website", "") or "").strip(),
        "payment_terms": to_int(vendor_details.get("payment_terms"), 0),
        "payment_terms_label": str(vendor_details.get("payment_terms_label", "") or "").strip(),
        "currency_id": vendor_details.get("currency_id"),
        "notes": str(vendor_details.get("notes", "") or "").strip(),
        "gst_no": str(vendor_details.get("gst_no", "") or "").strip(),
        "gst_treatment": str(vendor_details.get("gst_treatment", "") or "").strip(),
        "tax_treatment": str(vendor_details.get("tax_treatment", "") or "").strip(),
        "vat_treatment": str(vendor_details.get("vat_treatment", "") or "").strip(),
        "tax_reg_no": str(vendor_details.get("tax_reg_no", "") or "").strip(),
        "country_code": str(vendor_details.get("country_code", "") or "").strip(),
        "place_of_contact": str(vendor_details.get("place_of_contact", "") or "").strip(),
        "phone": str(vendor_details.get("phone", "") or "").strip(),
        "mobile": str(vendor_details.get("mobile", "") or "").strip(),
        "email": str(vendor_details.get("email", "") or "").strip(),
        "billing_address": {
            "attention": str(vendor_details.get("attention", "") or "").strip(),
            "address": str(vendor_details.get("address_line1", "") or vendor_details.get("address", "") or "").strip(),
            "street2": str(vendor_details.get("address_line2", "") or vendor_details.get("street2", "") or "").strip(),
            "city": str(vendor_details.get("city", "") or "").strip(),
            "state": str(vendor_details.get("state", "") or "").strip(),
            "zip": str(vendor_details.get("postal_code", "") or vendor_details.get("zip", "") or "").strip(),
            "country": str(vendor_details.get("country", "") or "").strip(),
            "phone": str(vendor_details.get("phone", "") or "").strip(),
        },
        "shipping_address": {
            "attention": str(vendor_details.get("attention", "") or "").strip(),
            "address": str(vendor_details.get("address_line1", "") or vendor_details.get("address", "") or "").strip(),
            "street2": str(vendor_details.get("address_line2", "") or vendor_details.get("street2", "") or "").strip(),
            "city": str(vendor_details.get("city", "") or "").strip(),
            "state": str(vendor_details.get("state", "") or "").strip(),
            "zip": str(vendor_details.get("postal_code", "") or vendor_details.get("zip", "") or "").strip(),
            "country": str(vendor_details.get("country", "") or "").strip(),
            "phone": str(vendor_details.get("phone", "") or "").strip(),
        }
    }

    return clean_empty_values(payload)


def clean_line_items_for_bill(line_items, extracted_data=None, taxes=None):
    cleaned_items = []

    if not isinstance(line_items, list):
        return cleaned_items

    extracted_data = extracted_data or {}
    taxes = taxes or []

    vendor_details = extracted_data.get("vendor_details", {})
    if not isinstance(vendor_details, dict):
        vendor_details = {}

    vendor_gst_no = str(vendor_details.get("gst_no", "") or extracted_data.get("gst_no", "") or "").strip()
    transaction_type = detect_transaction_type(vendor_gst_no)

    for index, item in enumerate(line_items, start=1):
        if not isinstance(item, dict):
            continue

        rate = to_float(item.get("rate"), 0)
        quantity = to_float(item.get("quantity"), 1)

        description = str(
            item.get("description", "") or
            item.get("name", "") or
            f"Invoice Item {index}"
        ).strip()

        account_id = str(item.get("account_id", "") or "").strip()
        if not account_id:
            account_id = DEFAULT_BILL_ACCOUNT_ID

        cleaned_item = {
            "account_id": account_id,
            "description": description,
            "rate": rate,
            "quantity": quantity,
        }

        tax_percentage = to_float(item.get("tax_percentage"), 0)
        line_item_taxes = find_matching_tax_ids(
            taxes=taxes,
            tax_percentage=tax_percentage,
            transaction_type=transaction_type
        )

        if line_item_taxes:
            cleaned_item["line_item_taxes"] = line_item_taxes

        cleaned_item = clean_empty_values(cleaned_item)

        if cleaned_item.get("account_id") and cleaned_item.get("description"):
            cleaned_items.append(cleaned_item)

    return cleaned_items


def prepare_bill_payload(extracted_data, vendor_id, source_file_name="", taxes=None):
    """
    Minimal bill payload:
    - vendor_id
    - date
    - bill_number (optional)
    - reference_number (optional)
    - line_items with account_id
    - dynamic line_item_taxes from Zoho tax API
    """
    if not DEFAULT_BILL_ACCOUNT_ID:
        raise Exception("DEFAULT_BILL_ACCOUNT_ID is missing in .env file")

    if not isinstance(extracted_data, dict):
        extracted_data = {}

    line_items = clean_line_items_for_bill(
        extracted_data.get("line_items", []),
        extracted_data=extracted_data,
        taxes=taxes or []
    )

    if not line_items:
        raise Exception(f"No valid line_items found for bill creation in file: {source_file_name}")

    raw_bill_date = str(extracted_data.get("date", "") or "").strip()
    if not raw_bill_date:
        raise Exception(f"Bill date is missing in extracted JSON for file: {source_file_name}")

    normalized_bill_date = normalize_zoho_date(raw_bill_date)

    payload = {
        "vendor_id": str(vendor_id),
        "date": normalized_bill_date,
        "bill_number": str(extracted_data.get("bill_number", "") or "").strip(),
        "reference_number": str(extracted_data.get("reference_number", "") or "").strip(),
        "line_items": line_items,
    }

    return clean_empty_values(payload)


def find_existing_vendor(api_base_url, organization_id, access_token, vendor_payload):
    search_candidates = []

    gst_no = vendor_payload.get("gst_no", "")
    email = vendor_payload.get("email", "")
    contact_name = vendor_payload.get("contact_name", "")

    if gst_no:
        search_candidates.append(gst_no)
    if email:
        search_candidates.append(email)
    if contact_name:
        search_candidates.append(contact_name)

    for candidate in search_candidates:
        encoded = urllib.parse.quote(candidate)
        url = (
            f"{api_base_url}/books/v3/contacts"
            f"?organization_id={organization_id}"
            f"&contact_type=vendor"
            f"&search_text={encoded}"
        )

        response_json = make_zoho_request(
            url=url,
            method="GET",
            access_token=access_token
        )

        contacts = response_json.get("contacts", [])
        if not isinstance(contacts, list):
            continue

        for contact in contacts:
            if not isinstance(contact, dict):
                continue

            existing_id = str(contact.get("contact_id", "") or "")
            if not existing_id:
                continue

            existing_gst = str(contact.get("gst_no", "") or "").strip().lower()
            existing_email = str(contact.get("email", "") or "").strip().lower()
            existing_name = str(contact.get("contact_name", "") or "").strip().lower()

            if gst_no and existing_gst and existing_gst == gst_no.strip().lower():
                return existing_id, contact

            if email and existing_email and existing_email == email.strip().lower():
                return existing_id, contact

            if contact_name and existing_name and existing_name == contact_name.strip().lower():
                return existing_id, contact

    return None, None


def create_vendor_in_zoho(api_base_url, organization_id, access_token, vendor_payload):
    existing_vendor_id, existing_vendor_data = find_existing_vendor(
        api_base_url=api_base_url,
        organization_id=organization_id,
        access_token=access_token,
        vendor_payload=vendor_payload
    )

    if existing_vendor_id:
        return existing_vendor_id, {
            "code": 0,
            "message": "Existing vendor reused",
            "contact": existing_vendor_data,
            "is_existing_vendor": True
        }

    url = f"{api_base_url}/books/v3/contacts?organization_id={organization_id}"

    response_json = make_zoho_request(
        url=url,
        method="POST",
        access_token=access_token,
        body=vendor_payload
    )

    if response_json.get("code") not in [0, "0"] and "contact" not in response_json:
        raise Exception(response_json.get("message", "Vendor creation failed"))

    contact_data = response_json.get("contact", {})
    vendor_id = str(contact_data.get("contact_id", "") or "")

    if not vendor_id:
        raise Exception("Vendor created but vendor_id not found in response")

    return vendor_id, response_json


def create_bill_in_zoho(api_base_url, organization_id, access_token, bill_payload):
    url = f"{api_base_url}/books/v3/bills?organization_id={organization_id}"

    response_json = make_zoho_request(
        url=url,
        method="POST",
        access_token=access_token,
        body=bill_payload
    )

    if response_json.get("code") not in [0, "0"] and "bill" not in response_json:
        raise Exception(response_json.get("message", "Bill creation failed"))

    return response_json


def process_single_file(uploaded_file, api_base_url, organization_id, access_token, taxes=None):
    file_result = {
        "file_name": uploaded_file.name,
        "status": "pending",
        "current_step": "started",
        "vendor_id": "",
        "bill_id": "",
        "extracted_json": {},
        "vendor_payload": {},
        "bill_payload": {},
        "vendor_response": {},
        "bill_response": {},
        "error": ""
    }

    try:
        file_result["current_step"] = "ocr_started"
        ocr_text = extract_text_from_file(uploaded_file)

        if not ocr_text or not str(ocr_text).strip():
            raise Exception("OCR did not return any text")

        file_result["current_step"] = "json_extraction_started"
        extracted_json_raw = convert_ocr_to_json(ocr_text, uploaded_file.name)
        extracted_json = parse_llm_json(extracted_json_raw)

        if not isinstance(extracted_json, dict):
            raise Exception("Extracted JSON must be an object/dictionary")

        file_result["extracted_json"] = extracted_json

        file_result["current_step"] = "vendor_payload_prepared"
        vendor_payload = prepare_vendor_payload(extracted_json)

        if not vendor_payload.get("contact_name"):
            raise Exception("Vendor name/contact_name is missing in extracted JSON")

        file_result["vendor_payload"] = vendor_payload

        file_result["current_step"] = "vendor_creation_started"
        vendor_id, vendor_response = create_vendor_in_zoho(
            api_base_url=api_base_url,
            organization_id=organization_id,
            access_token=access_token,
            vendor_payload=vendor_payload
        )
        file_result["vendor_id"] = vendor_id
        file_result["vendor_response"] = vendor_response

        file_result["current_step"] = "bill_payload_prepared"
        bill_payload = prepare_bill_payload(
            extracted_data=extracted_json,
            vendor_id=vendor_id,
            source_file_name=uploaded_file.name,
            taxes=taxes or []
        )
        file_result["bill_payload"] = bill_payload

        file_result["current_step"] = "bill_creation_started"
        bill_response = make_zoho_request(
            url=f"{api_base_url}/books/v3/bills?organization_id={organization_id}",
            method="POST",
            access_token=access_token,
            body=bill_payload
        )
        file_result["bill_response"] = bill_response

        if bill_response.get("code") not in [0, "0"] and "bill" not in bill_response:
            raise Exception(bill_response.get("message", "Bill creation failed"))

        bill_data = bill_response.get("bill", {})
        file_result["bill_id"] = str(bill_data.get("bill_id", "") or "")
        file_result["status"] = "success"
        file_result["current_step"] = "completed"

    except Exception as file_error:
        file_result["status"] = "failed"
        file_result["error"] = str(file_error)

    return file_result


def home(request):
    context = {
        "selected_doc_type": "Invoice"
    }

    if request.method == "POST":
        uploaded_files = request.FILES.getlist("pdfFiles")
        doc_type = request.POST.get("doc_type", "Invoice").strip()

        accounts_base_url = request.POST.get("accounts_base_url", "").strip()
        api_base_url = request.POST.get("api_base_url", "").strip()
        client_id = request.POST.get("client_id", "").strip()
        client_secret = request.POST.get("client_secret", "").strip()
        refresh_token = request.POST.get("refresh_token", "").strip()
        organization_id = request.POST.get("organization_id", "").strip()

        context["selected_doc_type"] = doc_type

        if not uploaded_files:
            context["error"] = "Please upload at least one file."
            return render(request, "home.html", context)

        if not all([accounts_base_url, api_base_url, client_id, client_secret, refresh_token, organization_id]):
            context["error"] = "Missing connection details. Please create connection again."
            return render(request, "home.html", context)

        try:
            access_token = get_access_token(
                accounts_base_url=accounts_base_url,
                client_id=client_id,
                client_secret=client_secret,
                refresh_token=refresh_token
            )

            # Fetch taxes once and reuse for all files
            taxes = fetch_tax_details(
                api_base_url=api_base_url,
                organization_id=organization_id,
                access_token=access_token
            )

            selected_files = [uploaded_file.name for uploaded_file in uploaded_files]
            processing_results = []

            for uploaded_file in uploaded_files:
                result = process_single_file(
                    uploaded_file=uploaded_file,
                    api_base_url=api_base_url,
                    organization_id=organization_id,
                    access_token=access_token,
                    taxes=taxes
                )
                processing_results.append(result)

            success_count = len([r for r in processing_results if r.get("status") == "success"])
            failed_count = len([r for r in processing_results if r.get("status") == "failed"])

            context["selected_files"] = selected_files
            context["results"] = processing_results
            context["success_count"] = success_count
            context["failed_count"] = failed_count
            context["formatted_json"] = json.dumps(processing_results, indent=4, ensure_ascii=False)

        except Exception as e:
            context["error"] = f"Error during processing: {str(e)}"

    return render(request, "home.html", context)


@require_POST
@csrf_exempt
def create_connection(request):
    try:
        data = json.loads(request.body)

        accounts_base_url = data.get("accounts_base_url", "").strip()
        api_base_url = data.get("api_base_url", "").strip()
        scope = data.get("scope", "").strip()
        client_id = data.get("client_id", "").strip()
        client_secret = data.get("client_secret", "").strip()
        refresh_token = data.get("refresh_token", "").strip()
        organization_id = data.get("organization_id", "").strip()

        if not all([accounts_base_url, api_base_url, scope, client_id, client_secret, refresh_token, organization_id]):
            return JsonResponse({
                "success": False,
                "message": "All fields are required."
            }, status=400)

        access_token = get_access_token(
            accounts_base_url=accounts_base_url,
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=refresh_token
        )

        # Verify tax API also, because bill creation depends on it
        taxes = fetch_tax_details(
            api_base_url=api_base_url,
            organization_id=organization_id,
            access_token=access_token
        )

        return JsonResponse({
            "success": True,
            "message": "Connection verified successfully.",
            "has_access_token": bool(access_token),
            "tax_count": len(taxes)
        })

    except Exception as e:
        return JsonResponse({
            "success": False,
            "message": str(e)
        }, status=500)