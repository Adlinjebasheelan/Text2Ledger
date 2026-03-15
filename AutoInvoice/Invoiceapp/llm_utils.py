import json
import re
from groq import Groq
from django.conf import settings


def convert_ocr_to_json(ocr_text, source_file_name=""):
    client = Groq(
        api_key=settings.GROQ_API_KEY
    )

    prompt = f"""
You are an expert invoice data extraction assistant.

You will receive OCR-extracted text from invoice documents.
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

Your job is to intelligently interpret the OCR text and extract the correct invoice information into a clean standardized JSON format.

IMPORTANT INSTRUCTIONS:
1. Return ONLY valid JSON.
2. Do not return markdown.
3. Do not return explanation text.
4. Use double quotes for all keys and string values.
5. Output must be directly parseable by Python json.loads().
6. If a field is not found, return an empty string.
7. If an array field is not found, return an empty array.
8. If OCR text is noisy, use surrounding context to identify likely field values.
9. Correct minor OCR mistakes only when the intended meaning is very clear.
10. Do NOT invent values without evidence.
11. Preserve values exactly when possible, especially numbers, invoice numbers, dates, tax percentages, and totals.
12. Recognize equivalent labels. Examples:
   - "Invoice No", "Invoice #", "Bill No", "Tax Invoice No" → invoice_number
   - "Bill To", "Customer", "Buyer" → customer_name / billing_address
   - "Ship To", "Delivery Address" → shipping_address
   - "Total", "Grand Total", "Invoice Total" → total_amount
   - "GST", "VAT", "Tax", "CGST", "SGST", "IGST" → tax-related fields
13. If totals are present, prioritize them carefully because they are business-critical.
14. If line items exist, extract them as accurately as possible.
15. If the same value appears multiple times, choose the value that best matches invoice context.
16. If source invoice does not contain a target-system field, keep it empty.
17. Put any extra useful extracted fields into "unmapped_fields".
18. Fill "meta.extraction_confidence" with one of these values only:
   - "high"
   - "medium"
   - "low"

EXTRACTION GUIDELINES:
- Customer details usually appear near labels like Bill To / Customer / Buyer.
- Vendor details usually appear near the top header, company name, address, phone, email, website, GST number.
- Invoice number is often near labels like Invoice No / Invoice # / Tax Invoice.
- Dates may appear in formats like DD/MM/YY, DD-MM-YYYY, YYYY-MM-DD.
- Currency may be shown as AED, INR, USD, SAR, etc.
- Totals often appear in a summary block near the bottom or right side.
- Bank details may appear near the footer or payment section.
- Notes may appear under "Notes", "Customer Notes", "Remarks", or similar.
- HSN/SAC may appear near item rows or tax descriptions.
- If a field value appears broken across lines, combine it logically.

JSON SCHEMA:
{{
  "customer_details": {{
    "customer_name": "",
    "billing_address": "",
    "shipping_address": "",
    "gst_treatment": "",
    "place_of_supply": "",
    "location": "",
    "associate_potential": ""
  }},
  "invoice_header": {{
    "invoice_number": "",
    "order_number": "",
    "invoice_date": "",
    "terms": "",
    "due_date": "",
    "currency": "",
    "accounts_receivable": "",
    "salesperson": "",
    "ecommerce_operator": "",
    "payment_type": "",
    "sales_order_number": "",
    "subject": "",
    "customer_notes": "",
    "custom_discount": "",
    "testing_custom_field": "",
    "warranty_end_date": ""
  }},
  "vendor_details": {{
    "vendor_name": "",
    "address": "",
    "phone": "",
    "email": "",
    "website": "",
    "gstin": ""
  }},
  "item_table": [
    {{
      "item_details": "",
      "description": "",
      "barcode_number": "",
      "hsn_sac": "",
      "warranty_period": "",
      "warranty_type": "",
      "warranty_start_date": "",
      "quantity": "",
      "rate": "",
      "tax": "",
      "tax_percent": "",
      "amount": "",
      "warehouse": "",
      "reporting_tags": "",
      "custom_fields": ""
    }}
  ],
  "totals": {{
    "subtotal": "",
    "discount": "",
    "discount_type": "",
    "shipping_charges": "",
    "cgst": "",
    "sgst": "",
    "igst": "",
    "tds": "",
    "tcs": "",
    "adjustment": "",
    "round_off": "",
    "total_amount": "",
    "payment_made": "",
    "balance_due": "",
    "total_in_words": ""
  }},
  "bank_details": {{
    "bank_name": "",
    "account_number": "",
    "ifsc_code": "",
    "branch": ""
  }},
  "meta": {{
    "invoice_type": "",
    "reference_number": "",
    "source_file_name": "",
    "extraction_confidence": ""
  }},
  "unmapped_fields": {{}}
}}

Now extract the invoice data from the OCR text below.

OCR TEXT:
{ocr_text}
"""

    response = client.chat.completions.create(
        model=settings.GROQ_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You extract invoice data and return only valid JSON. "
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

    # Remove markdown code fences if present
    if content.startswith("```json"):
        content = content.replace("```json", "", 1).strip()
    if content.startswith("```"):
        content = content.replace("```", "", 1).strip()
    if content.endswith("```"):
        content = content[:-3].strip()

    # Try direct JSON parsing first
    try:
        parsed = json.loads(content)
        if "meta" not in parsed:
            parsed["meta"] = {}
        parsed["meta"]["source_file_name"] = source_file_name
        return parsed
    except json.JSONDecodeError:
        pass

    # Try extracting JSON object from larger text
    try:
        match = re.search(r'\{.*\}', content, re.DOTALL)
        if match:
            json_text = match.group(0)
            parsed = json.loads(json_text)
            if "meta" not in parsed:
                parsed["meta"] = {}
            parsed["meta"]["source_file_name"] = source_file_name
            return parsed
    except json.JSONDecodeError:
        pass

    # Final fallback
    return {
        "customer_details": {
            "customer_name": "",
            "billing_address": "",
            "shipping_address": "",
            "gst_treatment": "",
            "place_of_supply": "",
            "location": "",
            "associate_potential": ""
        },
        "invoice_header": {
            "invoice_number": "",
            "order_number": "",
            "invoice_date": "",
            "terms": "",
            "due_date": "",
            "currency": "",
            "accounts_receivable": "",
            "salesperson": "",
            "ecommerce_operator": "",
            "payment_type": "",
            "sales_order_number": "",
            "subject": "",
            "customer_notes": "",
            "custom_discount": "",
            "testing_custom_field": "",
            "warranty_end_date": ""
        },
        "vendor_details": {
            "vendor_name": "",
            "address": "",
            "phone": "",
            "email": "",
            "website": "",
            "gstin": ""
        },
        "item_table": [],
        "totals": {
            "subtotal": "",
            "discount": "",
            "discount_type": "",
            "shipping_charges": "",
            "cgst": "",
            "sgst": "",
            "igst": "",
            "tds": "",
            "tcs": "",
            "adjustment": "",
            "round_off": "",
            "total_amount": "",
            "payment_made": "",
            "balance_due": "",
            "total_in_words": ""
        },
        "bank_details": {
            "bank_name": "",
            "account_number": "",
            "ifsc_code": "",
            "branch": ""
        },
        "meta": {
            "invoice_type": "",
            "reference_number": "",
            "source_file_name": source_file_name,
            "extraction_confidence": "",
            "parse_status": "failed",
            "parse_error": "LLM did not return valid JSON"
        },
        "unmapped_fields": {
            "raw_response": content
        }
    }