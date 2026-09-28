"""tools/managed-status.py — every managed dir: what a blank does, what the backup does."""
ID, LABEL, TITLE = "managed", "Managed", "managed dirs — blank level × backup class"
READER = "tools/managed-status.py"
REFRESH = 600
COLUMNS = ["var", "blank", "backup", "path", "why"]
DEMO = {"rows": [
    {"var": "stalwart_data_dir", "path": "~/nos/platform/services/stalwart/data",
     "blank": "data", "backup": "set", "why": ""},
    {"var": "qgis_data_dir", "path": "~/nos/platform/services/qgis/data",
     "blank": "data", "backup": "unbacked", "why": "GIS projects (opt-in service)"},
], "gaps": [], "counts": {"dirs": 2, "blank_data": 2, "backup_set": 1, "unbacked": 1, "undeclared": 0}}


def build_rows(data):
    rows = data.get("rows") or []
    # gaps first: a kept dir or a hole is what the operator opens this for
    return sorted(rows, key=lambda r: (r["blank"] == "data" and r["backup"] not in ("unbacked", "UNDECLARED"), r["var"]))


def meta(data):
    return data.get("counts")
