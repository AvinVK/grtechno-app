"""Wages (kohal, 2026-10-18: "when they login they should see attendance, wages and fooding. wages wont
be populated yet"): a placeholder page for a daily-wage worker's own wage tracking, which doesn't exist
yet - this just shows the day rate already on file for them (Worker.wage_amount, set from Employee
management) so the tile isn't a dead end, until day-by-day wage tracking is actually built. See
app/fooding.py, its sibling tile, for the same employment_type-gated shape."""

from flask import Blueprint, abort, g, jsonify, render_template

from .models import Worker, settings_for_client

bp = Blueprint("wages", __name__)


def _own_daily_wage_worker():
    worker = Worker.query.filter_by(user_code=g.user.code).first()
    if worker is None or worker.employment_type != "daily_wages":
        abort(403, "Wages is only for daily-wage employees.")
    return worker


@bp.get("/wages")
def page():
    _own_daily_wage_worker()
    return render_template("wages.html")


@bp.get("/api/wages/me")
def my_wages():
    worker = _own_daily_wage_worker()
    return jsonify(
        daily_rate=float(worker.wage_amount) if worker.wage_amount is not None else None,
        currency=settings_for_client()["currency"],
    )
