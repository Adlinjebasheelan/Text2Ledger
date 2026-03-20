import json
import re
from groq import Groq
from django.conf import settings


def convert_ocr_to_json(ocr_text, source_file_name=""):
    client = Groq(api_key=settings.GROQ_API_KEY)

    prompt = f"""
You are an expert invoice and bill data extraction assistant.

You will receive OCR-extracted text from invoice or bill documents.
The OCR text may contain errors such as:
- spelling mistakes
- broken words
- incorrect spacing
- merged lines
- missing punctuation
- misread characters (for example: O and 0, I and 1, S and 5)
- incorrect line breaks
- partially extracted labels
- duplicate text blocks

Your job is to intelligently interpret the OCR text and extract the correct bill/invoice information into a clean standardized JSON format.

IMPORTANT INSTRUCTIONS:
1. Return ONLY valid JSON.
2. Do not return markdown.
3. Do not return explanation text.
4. Use double quotes for all keys and string values.
5. Output must be directly parseable by Python json.loads().
6. If a field is not found, return an empty string for string fields.
7. If a numeric field is not found, return 0.
8. If a boolean field is not found, return false.
9. If an array field is not found, return an empty array.
10. If OCR text is noisy, use surrounding context to identify likely field values.
11. Correct minor OCR mistakes only when the intended meaning is very clear.
12. Do NOT invent values without evidence.
13. Preserve values exactly when possible, especially invoice numbers, dates, tax percentages, totals, GST/VAT numbers, and registration labels.
14. Extract line items as accurately as possible.
15. If the same value appears multiple times, choose the one that best matches invoice context.
16. Put unmapped useful values inside "unmapped_fields".
17. Include source file name inside documents array and also in unmapped_fields if useful.
18. Dates should be returned in YYYY-MM-DD format if clearly identifiable, otherwise return original value or empty string.
19. Numbers should be returned as numbers whenever clearly identifiable, not strings.
20. Return only one JSON object.
21. Do not create or assume any internal system IDs.
22. Predict gst_treatment and tax_treatment only from clear evidence in vendor details or invoice context.
23. If treatment cannot be inferred with reasonable confidence, return empty string.
24. Do not guess country-specific treatment unless country/region/tax context is visible in OCR text.

FIELD MAPPING GUIDELINES:
- Supplier / Vendor / Seller / From / Billed By -> vendor_details
- Bill No / Invoice No -> bill_number
- Reference No -> reference_number
- Invoice Date / Bill Date -> date
- Due Date -> due_date
- Payment Terms -> payment_terms_label
- Notes / Remarks -> notes
- Terms & Conditions -> terms
- GST No / GSTIN -> vendor_details.gst_no if clearly associated with vendor
- VAT No -> vendor_details.vat_no if clearly associated with vendor
- Place of Supply -> place_of_supply
- Source of Supply -> source_of_supply
- Destination of Supply / Ship To state -> destination_of_supply
- Line items -> line_items
- Tax summary -> taxes
- Subtotal / Taxable Amount -> subtotal
- Total Tax / GST Total / VAT Total -> total_tax
- Grand Total / Invoice Total / Bill Total -> total
- Balance Due / Amount Due -> balance_due

JSON SCHEMA:
{{
    "vendor_details": {{
        "name": "",
        "company_name": "",
        "gst_no": "",
        "vat_no": "",
        "gst_treatment": "",
        "tax_treatment": "",
        "email": "",
        "phone": "",
        "address_line1": "",
        "address_line2": "",
        "city": "",
        "state": "",
        "postal_code": "",
        "country": ""
    }},
    "bill_number": "",
    "documents": [
        {{
            "file_name": "{source_file_name}"
        }}
    ],
    "source_of_supply": "",
    "destination_of_supply": "",
    "place_of_supply": "",
    "reference_number": "",
    "date": "",
    "due_date": "",
    "payment_terms": 0,
    "payment_terms_label": "",
    "exchange_rate": 0,
    "is_item_level_tax_calc": false,
    "is_inclusive_tax": false,
    "subtotal": 0,
    "total_tax": 0,
    "adjustment": 0,
    "adjustment_description": "",
    "total": 0,
    "balance_due": 0,
    "currency_code": "",
    "line_items": [
        {{
            "name": "",
            "description": "",
            "rate": 0,
            "hsn_or_sac": "",
            "quantity": 0,
            "tax_name": "",
            "tax_percentage": 0,
            "item_order": 0,
            "product_type": "",
            "unit": "",
            "is_billable": false,
            "serial_numbers": []
        }}
    ],
    "taxes": [
        {{
            "tax_name": "",
            "tax_percentage": 0,
            "tax_amount": 0
        }}
    ],
    "notes": "",
    "terms": "",
    "unmapped_fields": {{}}
}}

EXTRACTION RULES FOR vendor_details:
- Extract supplier/vendor/seller/from/billed by details into vendor_details
- name = primary vendor display name
- company_name = legal/company name if separately available
- gst_no/vat_no = vendor tax registration if clearly associated with vendor
- email/phone/address = extract if available
- Do not invent missing values

PREDICTION RULES FOR vendor_details.gst_treatment:
- This field is India-only
- Allowed values: "business_gst", "business_none", "overseas", "consumer"
- Use "business_gst" when the vendor appears to be an Indian registered business and a valid GSTIN is present
- Use "business_none" when the vendor appears to be an Indian business but no GSTIN is present and business context is clear
- Use "consumer" when the vendor clearly appears to be an individual/consumer and not a registered business
- Use "overseas" when the vendor is clearly located outside India
- If not clear, return empty string

PREDICTION RULES FOR vendor_details.tax_treatment:
- Use only when the invoice context clearly indicates a VAT-based edition/country
- Allowed values may include:
  "vat_registered",
  "vat_not_registered",
  "gcc_vat_not_registered",
  "gcc_vat_registered",
  "non_gcc",
  "dz_vat_registered",
  "dz_vat_not_registered",
  "home_country_mexico",
  "border_region_mexico",
  "non_mexico",
  "non_kenya",
  "overseas"
- Infer from country, VAT number presence, invoice wording, and vendor address
- For GCC/UAE-style VAT context:
  - use "gcc_vat_registered" when vendor is in GCC and VAT registered
  - use "gcc_vat_not_registered" when vendor is in GCC and clearly not VAT registered
  - use "non_gcc" when vendor is outside GCC
  - use "vat_registered" / "vat_not_registered" when only generic VAT registration evidence is present
  - use "dz_vat_registered" / "dz_vat_not_registered" only if UAE-specific DZ context is clearly visible
- For Mexico:
  - use "home_country_mexico" when vendor is in Mexico in normal domestic context
  - use "border_region_mexico" only if border-region context is clearly visible
  - use "non_mexico" when vendor is outside Mexico
- For Kenya:
  - use "vat_registered" when vendor is in Kenya and VAT registered
  - use "vat_not_registered" when vendor is in Kenya and not VAT registered
  - use "non_kenya" when vendor is outside Kenya
- For South Africa:
  - use "vat_registered" when vendor is in South Africa and VAT registered
  - use "vat_not_registered" when vendor is in South Africa and not VAT registered
  - use "overseas" when vendor is outside South Africa
- If country/edition is unclear, return empty string

EXTRACTION RULES FOR line_items:
- name = item name or item details
- description = item description if available
- rate = item rate/unit price
- quantity = item quantity
- hsn_or_sac = HSN/SAC if available
- unit = unit such as pcs, kgs, nos, box, ltr, etc.
- tax_name = item-level tax label if available
- tax_percentage = numeric tax percentage if available
- item_order = row sequence starting from 1
- serial_numbers = extract if available, else empty array

EXTRACTION RULES FOR taxes:
- Extract tax rows from summary if available
- tax_name example: "CGST 9%", "SGST 9%", "VAT 5%"
- tax_percentage should be numeric when available
- tax_amount should be numeric
- If tax breakup not available, return empty array

Now extract the bill/invoice data from the OCR text below.

OCR TEXT:
{ocr_text}
"""

    response = client.chat.completions.create(
        model=settings.GROQ_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You extract invoice and bill data and return only valid JSON. "
                    "Never return markdown. Never return explanation. "
                    "Always use double quotes. Output must be valid JSON."
                )
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        temperature=0
    )

    content = response.choices[0].message.content.strip()

    if content.startswith("```json"):
        content = content.replace("```json", "", 1).strip()
    if content.startswith("```"):
        content = content.replace("```", "", 1).strip()
    if content.endswith("```"):
        content = content[:-3].strip()

    fallback_data = {
        "vendor_details": {
            "name": "",
            "company_name": "",
            "gst_no": "",
            "vat_no": "",
            "gst_treatment": "",
            "tax_treatment": "",
            "email": "",
            "phone": "",
            "address_line1": "",
            "address_line2": "",
            "city": "",
            "state": "",
            "postal_code": "",
            "country": ""
        },
        "bill_number": "",
        "documents": [
            {
                "file_name": source_file_name
            }
        ],
        "source_of_supply": "",
        "destination_of_supply": "",
        "place_of_supply": "",
        "reference_number": "",
        "date": "",
        "due_date": "",
        "payment_terms": 0,
        "payment_terms_label": "",
        "exchange_rate": 0,
        "is_item_level_tax_calc": False,
        "is_inclusive_tax": False,
        "subtotal": 0,
        "total_tax": 0,
        "adjustment": 0,
        "adjustment_description": "",
        "total": 0,
        "balance_due": 0,
        "currency_code": "",
        "line_items": [],
        "taxes": [],
        "notes": "",
        "terms": "",
        "unmapped_fields": {}
    }

    def deep_merge(default, parsed):
        if not isinstance(parsed, dict):
            return default

        merged = default.copy()

        for key, value in parsed.items():
            if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
                nested = merged[key].copy()
                nested.update(value)
                merged[key] = nested
            else:
                merged[key] = value

        return merged

    def merge_with_fallback(parsed):
        if not isinstance(parsed, dict):
            return fallback_data

        merged = deep_merge(fallback_data, parsed)

        if not isinstance(merged.get("vendor_details"), dict):
            merged["vendor_details"] = fallback_data["vendor_details"].copy()
        else:
            vendor_merged = fallback_data["vendor_details"].copy()
            vendor_merged.update(merged["vendor_details"])
            merged["vendor_details"] = vendor_merged

        if not isinstance(merged.get("documents"), list):
            merged["documents"] = []

        if not merged["documents"]:
            merged["documents"] = [{"file_name": source_file_name}]
        else:
            first_doc = merged["documents"][0]
            if not isinstance(first_doc, dict):
                first_doc = {}
            if not first_doc.get("file_name"):
                first_doc["file_name"] = source_file_name
            merged["documents"][0] = first_doc

        for list_key in ["documents", "line_items", "taxes"]:
            if not isinstance(merged.get(list_key), list):
                merged[list_key] = []

        if not isinstance(merged.get("unmapped_fields"), dict):
            merged["unmapped_fields"] = {}

        return merged

    try:
        parsed = json.loads(content)
        return merge_with_fallback(parsed)
    except json.JSONDecodeError:
        pass

    try:
        match = re.search(r'\{.*\}', content, re.DOTALL)
        if match:
            json_text = match.group(0)
            parsed = json.loads(json_text)
            return merge_with_fallback(parsed)
    except json.JSONDecodeError:
        pass

    fallback_data["unmapped_fields"] = {
        "raw_response": content,
        "parse_status": "failed",
        "parse_error": "LLM did not return valid JSON"
    }
    return fallback_data