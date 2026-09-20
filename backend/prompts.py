CLASSIFICATION_PROMPT = """
Classify this shipping operations email into exactly one category:

BL_COMPARISON
SI_REQUEST
INVOICE_QUERY
GENERAL
SPAM

Definitions:
- BL_COMPARISON: asks to check/verify/compare a Shipping Instruction (SI)
  against a draft Bill of Lading (BL).
- SI_REQUEST: asks for a new Shipping Instruction or SI preparation.
- INVOICE_QUERY: invoice, billing, charges, or payment question.
- GENERAL: normal operational/general message not covered above.
- SPAM: unsolicited or irrelevant spam.

Do not infer facts that are not present.
Return only the requested structured result.
"""


EXTRACTION_PROMPT = """
Extract shipping information from the supplied SI or BL text.

Use exactly these fields:
shipper
consignee
notify_party
port_of_loading
port_of_discharge
container_count
gross_weight_kg

Rules:
- Never invent a missing value.
- If a value cannot be reliably found, return null.
- container_count must be an integer when present.
- gross_weight_kg must be kilograms.
- Preserve meaningful company and port text.
- Return only the requested structured result.
"""