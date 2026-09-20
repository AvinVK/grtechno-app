"""Small helper for checking the fields of a JSON request, used by the clients and projects APIs.
Only fields that are present in the request are checked, so the same code serves create and partial update."""

from datetime import date
from decimal import Decimal, InvalidOperation

from flask import jsonify, request
from werkzeug.exceptions import HTTPException

MAX_MONEY = Decimal("99999999999")


class Fields:
    def __init__(self, payload: dict):
        self.payload = payload
        self.data = {}
        self.errors = {}

    def _has(self, name):
        return name in self.payload

    def text(self, name, limit, required=False, label=None):
        if not self._has(name):
            return
        value = self.payload[name]
        value = "" if value is None else value
        if not isinstance(value, str):
            self.errors[name] = "Enter text"
            return
        value = value.strip()
        if required and not value:
            self.errors[name] = f"Enter {label or name}"
        elif len(value) > limit:
            self.errors[name] = f"Keep this under {limit} characters"
        else:
            self.data[name] = value

    def choice(self, name, options):
        if self._has(name):
            if self.payload[name] in options:
                self.data[name] = self.payload[name]
            else:
                self.errors[name] = "Choose one of the options"

    def date(self, name):
        if not self._has(name):
            return
        raw = self.payload[name]
        if raw in (None, ""):
            self.data[name] = None
            return
        try:
            self.data[name] = date.fromisoformat(str(raw))
        except ValueError:
            self.errors[name] = "Pick a valid date"

    def integer(self, name, low=0, high=100000):
        if not self._has(name):
            return
        raw = self.payload[name]
        if raw in (None, ""):
            self.data[name] = None
            return
        try:
            number = int(str(raw))
        except ValueError:
            self.errors[name] = "Enter a whole number"
            return
        if low <= number <= high:
            self.data[name] = number
        else:
            self.errors[name] = f"Enter a number from {low} to {high}"

    def money(self, name, nullable=True):
        if not self._has(name):
            return
        raw = self.payload[name]
        if raw in (None, ""):
            if nullable:
                self.data[name] = None
            else:
                self.data[name] = Decimal("0.00")
            return
        self.data[name] = parse_money(raw, self.errors, name)
        if name in self.errors:
            self.data.pop(name, None)


def parse_money(raw, errors=None, name="amount"):
    try:
        amount = Decimal(str(raw))
        if not amount.is_finite() or amount < 0 or amount > MAX_MONEY:
            raise InvalidOperation
        return amount.quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        if errors is not None:
            errors[name] = "Enter a number, 0 or more"
        return None


def api_errors(blueprint):
    """JSON errors for /api/ paths of a blueprint that also serves pages."""
    @blueprint.errorhandler(HTTPException)
    def _handle(err):
        if request.path.startswith("/api/"):
            return jsonify(error=err.description or err.name), err.code
        return err
