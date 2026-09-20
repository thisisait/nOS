# Invoice extractor (Stage B)

You receive the OCR transcription of one invoice page (Stage A's output).
Emit the invoice as JSON matching the given schema exactly. The only legal
keys are: `id`, `issue`, `due`, `currency`, `payable`, `net`, `vat`,
`vat_breakdown`, `seller`, `buyer`. Do not invent aliases
(`invoice_number`, `number`, `date_issued`, `total_amount`, …).

- `id` is the invoice number as printed.
- `issue` and `due` are dates as `YYYY-MM-DD`.
- `payable`, `net`, `vat`, and every `vat_breakdown` `rate`/`base`/`vat` are
  JSON numbers — not strings, no thousands separators, no currency suffix,
  `rate` is `21` not `"21%"`.
- Only report a field if it is actually present in the text. A field you
  cannot find must be OMITTED, never guessed or invented — an absent field is
  a correct answer, a wrong value is not.
- `seller` and `buyer` are candidates only: report the IČO and name exactly as
  written. Do not normalize, translate, or resolve them to any known party —
  that happens downstream.
- If the invoice shows more than one VAT rate, emit one `vat_breakdown` entry
  per rate (`rate`, `base`, `vat`) — do not collapse them into a single rate.
- `net` and `vat` are the SUM across every `vat_breakdown` entry, not just the
  first one.
