# ERPNext — Skills

> Callable actions for ERPNext. Each skill is API-first using `openclaw-bot` API key.

## Authentication

- **Method:** API key + secret
- **Token:** `~/agents/tokens/erpnext.token`
- **Base URL:** `https://erp.dev.local`
- **Header:** `Authorization: token <api-key>:<api-secret>`

---

## list-documents

**Trigger:** "list customers", "show invoices", "get all items", "list [doctype]"
**Method:** API
**Endpoint:** `GET /api/resource/<Doctype>`
**Input:** Query params: `filters` (JSON), `fields` (JSON array), `limit_page_length` (optional), `order_by` (optional)
**Output:** `{ "data": [{ "name": "...", "field1": "...", "field2": "..." }] }`

**Example:**
```
"Show unpaid Sales Invoices"
GET /api/resource/Sales Invoice?filters=[["status","=","Unpaid"]]&fields=["name","customer","grand_total"]
```

---

## create-document

**Trigger:** "create customer", "add item", "new invoice", "create [doctype]"
**Method:** API
**Endpoint:** `POST /api/resource/<Doctype>`
**Input:**
```json
{
  "customer_name": "<name>",
  "customer_type": "Company",
  "territory": "Czech Republic"
}
```
**Output:** Created document object with `name`

---

## run-report

**Trigger:** "run report", "show sales summary", "generate report"
**Method:** API
**Endpoint:** `GET /api/method/frappe.client.get_report`
**Input:** Query params: `report_name`, `filters` (JSON)
**Output:** `{ "message": { "result": [...], "columns": [...] } }`

---

## get-doctype-list

**Trigger:** "list doctypes", "what data types exist", "show available modules"
**Method:** API
**Endpoint:** `GET /api/resource/DocType`
**Input:** Query params: `filters` (optional, e.g. `[["module","=","Selling"]]`), `fields` (optional)
**Output:** `{ "data": [{ "name": "Customer", "module": "Selling" }, { "name": "Sales Invoice", "module": "Accounts" }] }`
