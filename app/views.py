import csv
import io

from flask import Blueprint, Response, flash, redirect, render_template, request, url_for

from .auth import check_csrf
from .extensions import db
from .models import Lead, Setting
from .timeutil import today_local

bp = Blueprint("views", __name__)

CSV_COLUMNS = [
    ("id", "ID"),
    ("company", "Company"),
    ("contact_name", "Contact"),
    ("phone", "Phone"),
    ("email", "Email"),
    ("site_address", "Site address"),
    ("service", "Service"),
    ("source", "Source"),
    ("est_value", "Estimated value"),
    ("stage", "Stage"),
    ("follow_up_date", "Follow-up date"),
    ("notes", "Notes"),
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
    for lead in Lead.query.order_by(Lead.id).all():
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


def _clean_lines(text: str, limit: int = 60, width: int = 120) -> str:
    seen, out = set(), []
    for line in text.splitlines():
        line = line.strip()[:width]
        if line and line.lower() not in seen:
            seen.add(line.lower())
            out.append(line)
    return "\n".join(out[:limit])


@bp.route("/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        check_csrf()
        currency = request.form.get("currency", "").strip()[:5]
        country_code = "".join(ch for ch in request.form.get("country_code", "") if ch.isdigit())[:4]
        services = _clean_lines(request.form.get("services", ""))
        sources = _clean_lines(request.form.get("sources", ""))

        if not currency or not country_code or not services or not sources:
            flash("Fill in every field. Each list needs at least one entry.", "error")
        else:
            Setting.put("currency", currency)
            Setting.put("country_code", country_code)
            Setting.put("services", services)
            Setting.put("sources", sources)
            db.session.commit()
            flash("Settings saved.", "ok")
            return redirect(url_for("views.settings"))

    return render_template("settings.html", values=Setting.all())
