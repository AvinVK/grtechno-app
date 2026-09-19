from datetime import datetime, timezone

from .constants import DEFAULT_SETTINGS
from .extensions import db


def utcnow() -> datetime:
    """Naive UTC timestamp (SQLite has no timezone support)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso(dt):
    return dt.isoformat() + "Z" if dt else None


class User(db.Model):
    """A person who can sign in. The 4-digit code is the primary key and the tail of the userid
    (name-1234). Passwords and setup codes are stored only as hashes."""

    __tablename__ = "users"

    code = db.Column(db.String(4), primary_key=True)
    userid = db.Column(db.String(40), nullable=False, unique=True)
    name = db.Column(db.String(60), nullable=False)
    is_admin = db.Column(db.Boolean, nullable=False, default=False, server_default="0")
    is_active = db.Column(db.Boolean, nullable=False, default=True, server_default="1")
    password_hash = db.Column(db.String(255), nullable=True)
    setup_code_hash = db.Column(db.String(255), nullable=True)
    setup_code_expires = db.Column(db.DateTime, nullable=True)
    failed_attempts = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    locked_until = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    @property
    def status(self) -> str:
        if not self.is_active:
            return "off"
        return "active" if self.password_hash else "pending"


class Lead(db.Model):
    __tablename__ = "leads"

    id = db.Column(db.Integer, primary_key=True)
    contact_name = db.Column(db.String(120), nullable=False, default="")
    company = db.Column(db.String(160), nullable=False, default="")
    phone = db.Column(db.String(40), nullable=False, default="")
    email = db.Column(db.String(160), nullable=False, default="")
    site_pincode = db.Column(db.String(6), nullable=False, default="", server_default="")
    site_state = db.Column(db.String(80), nullable=False, default="", server_default="")
    site_district = db.Column(db.String(80), nullable=False, default="", server_default="")
    site_city = db.Column(db.String(120), nullable=False, default="", server_default="")
    site_address = db.Column(db.String(400), nullable=False, default="")
    service = db.Column(db.String(120), nullable=False, default="")
    source = db.Column(db.String(120), nullable=False, default="")
    est_value = db.Column(db.Numeric(14, 2), nullable=True)
    stage = db.Column(db.String(30), nullable=False, default="New enquiry", index=True)
    follow_up_date = db.Column(db.Date, nullable=True, index=True)
    notes = db.Column(db.Text, nullable=False, default="")
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)
    closed_at = db.Column(db.DateTime, nullable=True)
    owner_code = db.Column(db.String(4), db.ForeignKey("users.code", ondelete="SET NULL"), nullable=True, index=True)

    owner = db.relationship("User")
    activities = db.relationship(
        "Activity",
        back_populates="lead",
        cascade="all, delete-orphan",
        order_by="Activity.id.desc()",
    )

    def to_dict(self, with_activities: bool = False) -> dict:
        data = {
            "id": self.id,
            "contact_name": self.contact_name,
            "company": self.company,
            "phone": self.phone,
            "email": self.email,
            "site_pincode": self.site_pincode,
            "site_state": self.site_state,
            "site_district": self.site_district,
            "site_city": self.site_city,
            "site_address": self.site_address,
            "service": self.service,
            "source": self.source,
            "est_value": float(self.est_value) if self.est_value is not None else None,
            "stage": self.stage,
            "follow_up_date": self.follow_up_date.isoformat() if self.follow_up_date else None,
            "notes": self.notes,
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
            "closed_at": _iso(self.closed_at),
            "owner_name": self.owner.name if self.owner else None,
        }
        if with_activities:
            data["activities"] = [a.to_dict() for a in self.activities]
        return data


class Activity(db.Model):
    """Timeline entry on a lead: a typed note or an automatic change record."""

    __tablename__ = "activities"

    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(
        db.Integer, db.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind = db.Column(db.String(20), nullable=False, default="note")  # note | created | stage | followup
    text = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    lead = db.relationship("Lead", back_populates="activities")

    def to_dict(self) -> dict:
        return {"id": self.id, "kind": self.kind, "text": self.text, "created_at": _iso(self.created_at)}


class Pincode(db.Model):
    """Pincode to state / district / city. Filled from India Post the first time a pincode is used,
    then served from here. Rows can be corrected directly in the database."""

    __tablename__ = "pincodes"

    pincode = db.Column(db.String(6), primary_key=True)
    state = db.Column(db.String(80), nullable=False)
    district = db.Column(db.String(80), nullable=False)
    city = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)


class _NamedOption(db.Model):
    """One row per dropdown choice. Edit the rows directly in the database, the app only reads them."""

    __abstract__ = True

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    is_active = db.Column(db.Boolean, nullable=False, default=True, server_default="1")

    @classmethod
    def active_names(cls) -> list:
        rows = cls.query.filter_by(is_active=True).order_by(cls.sort_order, cls.name).all()
        return [r.name for r in rows]


class Service(_NamedOption):
    __tablename__ = "services"


class LeadSource(_NamedOption):
    __tablename__ = "lead_sources"


class Setting(db.Model):
    """Single-value app settings (currency, country_code), one row each. Edited in the database."""

    __tablename__ = "settings"

    key = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.Text, nullable=False, default="")

    @staticmethod
    def all() -> dict:
        stored = {s.key: s.value for s in Setting.query.all()}
        return {k: stored.get(k, default) for k, default in DEFAULT_SETTINGS.items()}


def settings_for_client() -> dict:
    s = Setting.all()
    return {
        "currency": s["currency"],
        "country_code": s["country_code"],
        "services": Service.active_names(),
        "sources": LeadSource.active_names(),
    }
