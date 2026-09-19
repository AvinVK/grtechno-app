import csv
import io

from flask import Blueprint, Response, render_template

from .auth import visible_leads
from .models import Lead
from .timeutil import today_local

bp = Blueprint("views", __name__)

CSV_COLUMNS = [
    ("id", "ID"),
    ("company", "Company"),
    ("contact_name", "Contact"),
    ("phone", "Phone"),
    ("email", "Email"),
    ("site_pincode", "Site pincode"),
    ("site_state", "State"),
    ("site_district", "District"),
    ("site_city", "City"),
    ("site_address", "Site address"),
    ("service", "Service"),
    ("source", "Source"),
    ("est_value", "Estimated value"),
    ("stage", "Stage"),
    ("follow_up_date", "Follow-up date"),
    ("notes", "Notes"),
    ("owner_name", "Owner"),
    ("created_at", "Created (UTC)"),
    ("closed_at", "Closed (UTC)"),
]


def _safe_cell(value):
    """Stop spreadsheet apps from running text such as =HYPERLINK(...) as a formula."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


@bp.get("/")
def index():
    return render_template("index.html")


@bp.get("/export.csv")
def export_csv():
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([label for _, label in CSV_COLUMNS])
    for lead in visible_leads().order_by(Lead.id).all():
        row = lead.to_dict()
        writer.writerow([_safe_cell("" if row[key] is None else row[key]) for key, _ in CSV_COLUMNS])

    # The BOM lets Excel read the currency symbol and non-English names correctly.
    body = "\ufeff" + buffer.getvalue()
    filename = f"leads-{today_local().isoformat()}.csv"
    return Response(
        body,
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
