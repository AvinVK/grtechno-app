import json
from datetime import datetime, timezone
from decimal import Decimal

from .constants import DEFAULT_SETTINGS
from .crypto import EncryptedText
from .extensions import db


def utcnow() -> datetime:
    """Naive UTC timestamp (SQLite has no timezone support)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso(dt):
    return dt.isoformat() + "Z" if dt else None


# A lead or project can call for more than one service (e.g. an AMC plus a Fire NOC in the same enquiry) -
# plain association tables, no extra columns needed on either side of the link.
lead_services = db.Table(
    "lead_services",
    db.Column("lead_id", db.Integer, db.ForeignKey("leads.id", ondelete="CASCADE"), primary_key=True),
    db.Column("service_id", db.Integer, db.ForeignKey("services.id", ondelete="CASCADE"), primary_key=True),
)

project_services = db.Table(
    "project_services",
    db.Column("project_id", db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
    db.Column("service_id", db.Integer, db.ForeignKey("services.id", ondelete="CASCADE"), primary_key=True),
)


class User(db.Model):
    """A person who can sign in. The 4-digit code is the primary key and the tail of the userid
    (name-1234). PINs and setup codes are stored only as hashes."""

    __tablename__ = "users"

    code = db.Column(db.String(4), primary_key=True)
    userid = db.Column(db.String(40), nullable=False, unique=True)
    name = db.Column(db.String(60), nullable=False)
    is_admin = db.Column(db.Boolean, nullable=False, default=False, server_default="0")
    is_active = db.Column(db.Boolean, nullable=False, default=True, server_default="1")
    phone = db.Column(EncryptedText, nullable=True)
    password_hash = db.Column(db.String(255), nullable=True)
    setup_code_hash = db.Column(db.String(255), nullable=True)
    setup_code_expires = db.Column(db.DateTime, nullable=True)
    failed_attempts = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    locked_until = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    role_key = db.Column(db.String(30), db.ForeignKey("roles.key"), nullable=True)

    role = db.relationship("Role")
    states = db.relationship("UserState", cascade="all, delete-orphan", order_by="UserState.state")

    @property
    def sees_all(self) -> bool:
        """The admin, and any role marked sees_all (for example Accounts), see every client and project."""
        return bool(self.is_admin or (self.role and self.role.sees_all))

    @property
    def state_names(self) -> list:
        return [s.state for s in self.states]

    @property
    def status(self) -> str:
        if not self.is_active:
            return "off"
        return "active" if self.password_hash else "pending"


class UserState(db.Model):
    """One state a sub-admin can see clients and projects for (visible_clients/visible_projects in auth.py).
    Only meaningful for role_key 'sub_admin' - a role change away just leaves these unused, not deleted,
    in case they're moved back."""

    __tablename__ = "user_states"

    user_code = db.Column(db.String(4), db.ForeignKey("users.code", ondelete="CASCADE"), primary_key=True)
    state = db.Column(db.String(80), primary_key=True)


class Lead(db.Model):
    __tablename__ = "leads"

    id = db.Column(db.Integer, primary_key=True)
    contact_name = db.Column(db.String(120), nullable=False, default="")
    company = db.Column(db.String(160), nullable=False, default="")
    phone = db.Column(EncryptedText, nullable=False, default="")
    email = db.Column(EncryptedText, nullable=False, default="")
    service = db.Column(db.String(120), nullable=False, default="")  # legacy: pre-multi-service leads only
    source = db.Column(db.String(120), nullable=False, default="")
    est_value = db.Column(db.Numeric(14, 2), nullable=True)  # set at Quote sent, not at creation, for new leads
    stage = db.Column(db.String(30), nullable=False, default="New enquiry", index=True)
    follow_up_date = db.Column(db.Date, nullable=True, index=True)
    notes = db.Column(db.Text, nullable=False, default="")
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)
    closed_at = db.Column(db.DateTime, nullable=True)
    owner_code = db.Column(db.String(4), db.ForeignKey("users.code", ondelete="SET NULL"), nullable=True, index=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=True, index=True)
    quote_sent_date = db.Column(db.Date, nullable=True)
    work_order_no = db.Column(db.String(60), nullable=False, default="", server_default="")
    work_order_date = db.Column(db.Date, nullable=True)
    advance_amount = db.Column(db.Numeric(14, 2), nullable=True)
    advance_date = db.Column(db.Date, nullable=True)
    advance_mode = db.Column(db.String(40), nullable=False, default="", server_default="")
    advance_comments = db.Column(db.Text, nullable=False, default="", server_default="")
    enquired_by_id = db.Column(db.Integer, db.ForeignKey("workers.id", ondelete="SET NULL"), nullable=True)

    owner = db.relationship("User")
    client = db.relationship("Client")
    enquired_by = db.relationship("Worker", foreign_keys=[enquired_by_id])
    services = db.relationship("Service", secondary=lead_services)
    activities = db.relationship(
        "Activity",
        back_populates="lead",
        cascade="all, delete-orphan",
        order_by="Activity.id.desc()",
    )
    project = db.relationship("Project", back_populates="lead", uselist=False)
    survey = db.relationship("LeadSurvey", back_populates="lead", uselist=False, cascade="all, delete-orphan")
    negotiations = db.relationship(
        "LeadNegotiation", back_populates="lead", cascade="all, delete-orphan",
        order_by="LeadNegotiation.round_no",
    )

    def to_dict(self, with_activities: bool = False) -> dict:
        service_names = [s.name for s in self.services] if self.services else ([self.service] if self.service else [])
        data = {
            "id": self.id,
            "contact_name": self.contact_name,
            "company": self.company,
            "phone": self.phone,
            "email": self.email,
            "service": self.service,
            "services": service_names,
            "source": self.source,
            "est_value": float(self.est_value) if self.est_value is not None else None,
            "stage": self.stage,
            "follow_up_date": self.follow_up_date.isoformat() if self.follow_up_date else None,
            "notes": self.notes,
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
            "closed_at": _iso(self.closed_at),
            "owner_name": self.owner.name if self.owner else None,
            "project_id": self.project.id if self.project else None,
            "client_id": self.client_id,
            "client_name": self.client.name if self.client else None,
            "quote_sent_date": self.quote_sent_date.isoformat() if self.quote_sent_date else None,
            "work_order_no": self.work_order_no,
            "work_order_date": self.work_order_date.isoformat() if self.work_order_date else None,
            "advance_amount": float(self.advance_amount) if self.advance_amount is not None else None,
            "advance_date": self.advance_date.isoformat() if self.advance_date else None,
            "advance_mode": self.advance_mode,
            "advance_comments": self.advance_comments,
            "enquired_by_id": self.enquired_by_id,
            "enquired_by_name": self.enquired_by.name if self.enquired_by else None,
            "survey": self.survey.to_dict() if self.survey else None,
            "negotiations": [n.to_dict() for n in self.negotiations],
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


class LeadSurvey(db.Model):
    """The one site survey done for a lead: when, who from the staff list went, and who they met on
    site. Moving a lead to Quote sent requires this to exist with a date."""

    __tablename__ = "lead_surveys"

    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, unique=True)
    survey_date = db.Column(db.Date, nullable=True)
    surveyor_id = db.Column(db.Integer, db.ForeignKey("workers.id", ondelete="SET NULL"), nullable=True)
    rep_name = db.Column(db.String(120), nullable=False, default="", server_default="")
    rep_role = db.Column(db.String(60), nullable=False, default="", server_default="")
    rep_phone = db.Column(db.String(40), nullable=False, default="", server_default="")
    # What tells this site apart from another at the same client - a client can go on to have more than
    # one project, each at its own site, and this is the one thing that distinguishes them anywhere a lead
    # or project is listed (see title() in app.js and Project.title below).
    site_name = db.Column(db.String(160), nullable=False, default="", server_default="")
    site_category = db.Column(db.String(60), nullable=False, default="", server_default="")
    site_pincode = db.Column(db.String(6), nullable=False, default="", server_default="")
    site_state = db.Column(db.String(80), nullable=False, default="", server_default="")
    site_district = db.Column(db.String(80), nullable=False, default="", server_default="")
    site_city = db.Column(db.String(120), nullable=False, default="", server_default="")
    site_address = db.Column(EncryptedText, nullable=False, default="")
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    lead = db.relationship("Lead", back_populates="survey")
    surveyor = db.relationship("Worker")
    photos = db.relationship(
        "SurveyPhoto", back_populates="survey", cascade="all, delete-orphan", order_by="SurveyPhoto.id",
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "survey_date": self.survey_date.isoformat() if self.survey_date else None,
            "surveyor_id": self.surveyor_id,
            "surveyor_name": self.surveyor.name if self.surveyor else None,
            "rep_name": self.rep_name, "rep_role": self.rep_role, "rep_phone": self.rep_phone,
            "site_name": self.site_name,
            "site_category": self.site_category, "site_pincode": self.site_pincode,
            "site_state": self.site_state, "site_district": self.site_district, "site_city": self.site_city,
            "site_address": self.site_address,
            "photos": [p.to_dict() for p in self.photos],
        }


class SurveyPhoto(db.Model):
    """One photo taken during a site survey. filename is the random name it's stored under, never the
    original - see app/uploads.py."""

    __tablename__ = "survey_photos"

    id = db.Column(db.Integer, primary_key=True)
    survey_id = db.Column(db.Integer, db.ForeignKey("lead_surveys.id", ondelete="CASCADE"), nullable=False, index=True)
    filename = db.Column(db.String(80), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    survey = db.relationship("LeadSurvey", back_populates="photos")

    def to_dict(self) -> dict:
        return {"id": self.id, "url": f"/uploads/survey/{self.filename}"}


class LeadNegotiation(db.Model):
    """One round of a lead's negotiation, repeated as many times as it takes until it's marked won or
    lost. round_no just numbers them in order for display."""

    __tablename__ = "lead_negotiations"

    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)
    round_no = db.Column(db.Integer, nullable=False)
    date = db.Column(db.Date, nullable=True)
    authorized_person = db.Column(db.String(120), nullable=False, default="", server_default="")
    estimate = db.Column(db.Numeric(14, 2), nullable=True)
    finalized = db.Column(db.Boolean, nullable=False, default=False, server_default="0")
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    lead = db.relationship("Lead", back_populates="negotiations")

    def to_dict(self) -> dict:
        return {
            "id": self.id, "round_no": self.round_no,
            "date": self.date.isoformat() if self.date else None,
            "authorized_person": self.authorized_person,
            "estimate": float(self.estimate) if self.estimate is not None else None,
            "finalized": self.finalized,
        }


class Role(db.Model):
    """What a kind of user is called and whether they see every client and project. Edited in the database."""

    __tablename__ = "roles"

    key = db.Column(db.String(30), primary_key=True)
    name = db.Column(db.String(60), nullable=False)
    sees_all = db.Column(db.Boolean, nullable=False, default=False, server_default="0")


class RoleModule(db.Model):
    """Which services a role can open (the admin can open all of them), and whether that's look-only -
    Accountant and Office Assistant can open Users & roles and Employee management to see them, but not
    add, edit or remove anything there; everywhere else write_access is left at its default, True."""

    __tablename__ = "role_modules"

    role_key = db.Column(db.String(30), db.ForeignKey("roles.key", ondelete="CASCADE"), primary_key=True)
    module_key = db.Column(db.String(30), db.ForeignKey("modules.key", ondelete="CASCADE"), primary_key=True)
    write_access = db.Column(db.Boolean, nullable=False, default=True, server_default="1")


class Client(db.Model):
    """A customer. Only ever created automatically when a lead is won - never added by hand - and kept for
    every project done for them; one client can go on to have several projects over time."""

    __tablename__ = "clients"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    contact_name = db.Column(db.String(120), nullable=False, default="", server_default="")
    phone = db.Column(EncryptedText, nullable=False, default="", server_default="")
    email = db.Column(EncryptedText, nullable=False, default="", server_default="")
    site_name = db.Column(db.String(160), nullable=False, default="", server_default="")
    site_category = db.Column(db.String(60), nullable=False, default="", server_default="")
    pincode = db.Column(db.String(6), nullable=False, default="", server_default="")
    state = db.Column(db.String(80), nullable=False, default="", server_default="")
    district = db.Column(db.String(80), nullable=False, default="", server_default="")
    city = db.Column(db.String(120), nullable=False, default="", server_default="")
    address = db.Column(EncryptedText, nullable=False, default="", server_default="")
    notes = db.Column(db.Text, nullable=False, default="", server_default="")
    owner_code = db.Column(db.String(4), db.ForeignKey("users.code", ondelete="SET NULL"), nullable=True, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    owner = db.relationship("User")
    projects = db.relationship("Project", back_populates="client", order_by="Project.id.desc()")

    @property
    def total_estimated_value(self):
        amounts = [p.estimated_amount for p in self.projects if p.estimated_amount is not None]
        return sum(amounts) if amounts else None

    def to_dict(self) -> dict:
        services = sorted({name for p in self.projects for name in p.service_names})
        return {
            "id": self.id, "name": self.name, "contact_name": self.contact_name, "phone": self.phone,
            "email": self.email, "site_name": self.site_name, "site_category": self.site_category, "pincode": self.pincode,
            "state": self.state, "district": self.district, "city": self.city, "address": self.address,
            "notes": self.notes, "owner_name": self.owner.name if self.owner else None,
            "project_count": len(self.projects), "services": services,
            "total_estimated_value": float(self.total_estimated_value) if self.total_estimated_value is not None else None,
            "created_at": _iso(self.created_at),
        }


class Project(db.Model):
    """A piece of work for a client, usually created when a lead is won."""

    __tablename__ = "projects"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=False, index=True)
    lead_id = db.Column(db.Integer, db.ForeignKey("leads.id", ondelete="SET NULL"), nullable=True, unique=True)
    title = db.Column(db.String(160), nullable=False)
    site_name = db.Column(db.String(160), nullable=False, default="", server_default="")
    work_category = db.Column(db.String(120), nullable=False, default="", server_default="")
    status = db.Column(db.String(20), nullable=False, default="planned", server_default="planned", index=True)
    site_pincode = db.Column(db.String(6), nullable=False, default="", server_default="")
    site_state = db.Column(db.String(80), nullable=False, default="", server_default="")
    site_district = db.Column(db.String(80), nullable=False, default="", server_default="")
    site_city = db.Column(db.String(120), nullable=False, default="", server_default="")
    site_address = db.Column(EncryptedText, nullable=False, default="", server_default="")
    work_order_no = db.Column(db.String(60), nullable=False, default="", server_default="")
    work_order_date = db.Column(db.Date, nullable=True)
    start_date = db.Column(db.Date, nullable=True)
    completion_days = db.Column(db.Integer, nullable=True)
    estimated_amount = db.Column(db.Numeric(14, 2), nullable=True)
    discount_amount = db.Column(db.Numeric(14, 2), nullable=False, default=0, server_default="0")
    # Set at closing time, from the final on-site measurement - once present it's the figure that counts,
    # not the negotiated estimate (the work actually done can come in more or less than what was quoted).
    final_amount = db.Column(db.Numeric(14, 2), nullable=True)
    payment_terms = db.Column(db.Text, nullable=False, default="", server_default="")
    special_terms = db.Column(db.Text, nullable=False, default="", server_default="")
    manager_code = db.Column(db.String(4), db.ForeignKey("users.code", ondelete="SET NULL"), nullable=True, index=True)
    owner_code = db.Column(db.String(4), db.ForeignKey("users.code", ondelete="SET NULL"), nullable=True, index=True)
    completed_at = db.Column(db.DateTime, nullable=True)          # set when it is closed (status completed)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    client = db.relationship("Client", back_populates="projects")
    lead = db.relationship("Lead", back_populates="project")
    manager = db.relationship("User", foreign_keys=[manager_code])
    owner = db.relationship("User", foreign_keys=[owner_code])
    services = db.relationship("Service", secondary=project_services)
    payments = db.relationship(
        "ProjectPayment", back_populates="project", cascade="all, delete-orphan",
        order_by="ProjectPayment.position, ProjectPayment.id",
    )

    @property
    def code(self) -> str:
        return f"PRJ-{self.id:04d}"

    @property
    def net_amount(self):
        if self.final_amount is not None:
            return self.final_amount
        if self.estimated_amount is None:
            return None
        return self.estimated_amount - (self.discount_amount or 0)

    @property
    def paid_amount(self):
        """What's actually been received - the payment steps with a date of payment recorded, not every
        step in the schedule (a future step can sit there unpaid)."""
        return sum((p.amount for p in self.payments if p.paid_date is not None), Decimal(0))

    @property
    def service_names(self) -> list:
        """The services this project covers - the new multi-service list if it has one, else the old
        single work_category string for a project created before that existed."""
        if self.services:
            return [s.name for s in self.services]
        return [self.work_category] if self.work_category else []

    def to_dict(self, detail: bool = False) -> dict:
        def num(v):
            return float(v) if v is not None else None

        data = {
            "id": self.id, "code": self.code, "title": self.title, "site_name": self.site_name, "status": self.status,
            "work_category": self.work_category, "services": self.service_names,
            "client_id": self.client_id, "client_name": self.client.name,
            "estimated_amount": num(self.estimated_amount), "discount_amount": num(self.discount_amount),
            "final_amount": num(self.final_amount), "net_amount": num(self.net_amount),
            "paid_amount": num(self.paid_amount), "manager_code": self.manager_code,
            "manager_name": self.manager.name if self.manager else None,
            "lead_id": self.lead_id,
            "site_state": self.site_state, "site_district": self.site_district, "site_city": self.site_city,
        }
        if detail:
            data.update({
                "site_pincode": self.site_pincode, "site_address": self.site_address,
                "work_order_no": self.work_order_no,
                "work_order_date": self.work_order_date.isoformat() if self.work_order_date else None,
                "start_date": self.start_date.isoformat() if self.start_date else None,
                "completion_days": self.completion_days,
                "payment_terms": self.payment_terms, "special_terms": self.special_terms,
                "payments": [p.to_dict() for p in self.payments],
            })
        return data


class ProjectPayment(db.Model):
    """One step of a project's payment schedule (advance, on delivery, on completion, ...)."""

    __tablename__ = "project_payments"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    label = db.Column(db.String(120), nullable=False)
    amount = db.Column(db.Numeric(14, 2), nullable=False, default=0, server_default="0")
    due_date = db.Column(db.Date, nullable=True)
    position = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    mode = db.Column(db.String(40), nullable=False, default="", server_default="")
    paid_date = db.Column(db.Date, nullable=True)
    comments = db.Column(db.Text, nullable=False, default="", server_default="")

    project = db.relationship("Project", back_populates="payments")

    def to_dict(self) -> dict:
        return {
            "label": self.label, "amount": float(self.amount),
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "mode": self.mode,
            "paid_date": self.paid_date.isoformat() if self.paid_date else None,
            "comments": self.comments,
        }


class Material(db.Model):
    """One kind of stock the business buys and uses on projects (cement, pipes, valves...), admin only for
    now. Stock on hand and its cost are kept right here, moved only through MaterialMovement entries below -
    a running balance, the same way a bank balance isn't re-summed from every transaction each time someone
    checks it. avg_rate is a weighted average cost per unit: a stock-in blends its own rate into it; usage
    just draws down the quantity at whatever that average already is, so it never needs a rate typed in."""

    __tablename__ = "materials"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    unit = db.Column(db.String(20), nullable=False, default="", server_default="")   # bags, kg, pcs, mtr...
    stock_qty = db.Column(db.Numeric(14, 2), nullable=False, default=0, server_default="0")
    avg_rate = db.Column(db.Numeric(14, 2), nullable=False, default=0, server_default="0")
    notes = db.Column(db.String(400), nullable=False, default="", server_default="")
    # How often this material goes into a job - "every_project" / "special_project" / "occasional", or ""
    # for not set yet. A small fixed set (see app/inventory.py's FREQUENCY_CHOICES), so this stores the key,
    # not a display label.
    frequency = db.Column(db.String(20), nullable=False, default="", server_default="")
    # Which fire-protection system(s) it's used in - Hydrant, Pump house, Sprinkler, Fire alarm, Portable
    # devices, or a typed-in "Other" - a material can span more than one, so this is a JSON list of strings
    # in a plain text column rather than its own table; see Material.used_in_list / app/inventory.py.
    used_in = db.Column(db.Text, nullable=False, default="", server_default="")
    is_active = db.Column(db.Boolean, nullable=False, default=True, server_default="1")
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    movements = db.relationship(
        "MaterialMovement", back_populates="material", cascade="all, delete-orphan",
        order_by="MaterialMovement.entry_date.desc(), MaterialMovement.id.desc()",
    )

    @property
    def code(self) -> str:
        # The item's own business key - shown everywhere instead of the raw database id. Derived from id,
        # like Project.code, so it's unique and immutable for free - no stored column to keep in sync.
        return f"MAT-{self.id:04d}"

    @property
    def stock_value(self):
        return (self.stock_qty * self.avg_rate).quantize(Decimal("0.01"))

    @property
    def used_in_list(self) -> list:
        return json.loads(self.used_in) if self.used_in else []

    @property
    def pending_requested_qty(self) -> Decimal:
        """Still owed to pending issue requests (kohal, 2026-10-17: "a flag for that material saying we need
        min of 2 of these next time we stock in") - the total a stock-in should cover at minimum to clear
        every project waiting on this material, not just get stock_qty back above zero."""
        return sum((mv.quantity for mv in self.movements if mv.kind == "out" and mv.status == "pending"),
                   start=Decimal("0"))

    def to_dict(self) -> dict:
        return {
            "id": self.id, "code": self.code, "name": self.name, "unit": self.unit,
            "stock_qty": float(self.stock_qty), "avg_rate": float(self.avg_rate),
            "stock_value": float(self.stock_value), "notes": self.notes, "is_active": self.is_active,
            "frequency": self.frequency, "used_in": self.used_in_list,
            "pending_requested_qty": float(self.pending_requested_qty),
        }


class Supplier(db.Model):
    """Who a material was bought from - its own short list (like Role), built up as stock-in entries name
    a new one, rather than typed fresh every time."""

    __tablename__ = "suppliers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False, unique=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)


class MaterialUnit(db.Model):
    """The unit a material is counted in (Meter, EA, LOT...) - its own short list, same idea as Supplier,
    seeded with the usual set and grown whenever someone types a new one on Add/Edit material. Material.unit
    itself stays a plain string (see Material) - this table only backs the picker's suggestions, so a typo
    or a one-off unit never needs a migration."""

    __tablename__ = "material_units"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(20), nullable=False, unique=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)


class MaterialMovement(db.Model):
    """One stock-in (a purchase or receipt) or stock-out (issued to a project) entry for a material - a
    ledger, so the stock and value on the Material row can always be traced back to where they came from
    or where they went.

    Some movements need sign-off before they count: a stock-in ('in') from someone who isn't themselves an
    accountant/office assistant needs approval from one (kohal, 2026-10-16). An issue ('out') always starts
    as a request now (kohal, 2026-10-17) - approved from Inventory's own Material requests tab by anyone
    with Inventory access, who records there who physically took it out, how it was transported and when
    (given_by_worker_id/transport_mode/transported_at) - a direct issue from Inventory itself (not a
    project's request) still goes straight to 'approved', since whoever's doing it is already the one
    handing it over. Approving less than what was asked for (not enough in stock) splits the request: this
    row becomes the approved amount, and a new 'pending' row for the shortfall takes its place, surfacing
    again once there's enough stock - see inventory.py's approve_issue_request.

    A movement stays `status='pending'` - excluded from _recompute_material's replay, so it has no effect on
    stock_qty/avg_rate at all - until approved. Rejected the same way, permanently. Every movement from
    before any of this existed is 'approved'."""

    __tablename__ = "material_movements"

    id = db.Column(db.Integer, primary_key=True)
    material_id = db.Column(db.Integer, db.ForeignKey("materials.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = db.Column(db.String(10), nullable=False)                                        # in | out
    quantity = db.Column(db.Numeric(14, 2), nullable=False)
    rate = db.Column(db.Numeric(14, 2), nullable=False, default=0, server_default="0")      # purchase cost per unit
    amount = db.Column(db.Numeric(14, 2), nullable=False, default=0, server_default="0")    # quantity * rate, pre-GST
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True)
    note = db.Column(db.String(200), nullable=False, default="", server_default="")         # "Remarks"
    entry_date = db.Column(db.Date, nullable=False)
    # Stock-in only (a material can be bought from a different supplier, on different terms, each time, so
    # these live on the movement, not the material itself) - stock on hand is still valued at `rate`
    # (pre-GST), unaffected by any of this; it's kept purely for the paper trail.
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True, index=True)
    bill_no = db.Column(db.String(60), nullable=False, default="", server_default="")
    payment_mode = db.Column(db.String(10), nullable=False, default="", server_default="")  # credit | cash
    gst_percent = db.Column(db.Numeric(5, 2), nullable=False, default=0, server_default="0")
    gst_amount = db.Column(db.Numeric(14, 2), nullable=False, default=0, server_default="0")    # amount * gst_percent / 100
    total_cost = db.Column(db.Numeric(14, 2), nullable=False, default=0, server_default="0")    # amount + gst_amount
    bill_filename = db.Column(db.String(80), nullable=True)
    # Issue (stock-out) only - who physically took the material out of the store, not who happened to be
    # signed in and recorded the entry (created_by_code, below); how it got from the store to the project,
    # and when that actually happened - filled in at approval time for a request, or on the spot for a
    # direct issue (kohal, 2026-10-17).
    given_by_worker_id = db.Column(db.Integer, db.ForeignKey("workers.id", ondelete="SET NULL"), nullable=True, index=True)
    transport_mode = db.Column(db.String(40), nullable=False, default="", server_default="")
    transported_at = db.Column(db.DateTime, nullable=True)
    created_by_code = db.Column(db.String(4), db.ForeignKey("users.code", ondelete="SET NULL"), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    # Approval (see the class docstring) - pending | approved | rejected.
    status = db.Column(db.String(10), nullable=False, default="approved", server_default="approved")
    approved_by_code = db.Column(db.String(4), db.ForeignKey("users.code", ondelete="SET NULL"), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)

    material = db.relationship("Material", back_populates="movements")
    project = db.relationship("Project")
    supplier = db.relationship("Supplier")
    given_by = db.relationship("Worker")
    created_by = db.relationship("User", foreign_keys=[created_by_code])
    approved_by = db.relationship("User", foreign_keys=[approved_by_code])

    def to_dict(self) -> dict:
        return {
            "id": self.id, "material_id": self.material_id, "kind": self.kind,
            "quantity": float(self.quantity), "rate": float(self.rate), "amount": float(self.amount),
            "project_id": self.project_id, "project_title": self.project.title if self.project else None,
            "project_code": self.project.code if self.project else None,
            "note": self.note, "entry_date": self.entry_date.isoformat(),
            "supplier_id": self.supplier_id, "supplier_name": self.supplier.name if self.supplier else None,
            "bill_no": self.bill_no, "payment_mode": self.payment_mode,
            "gst_percent": float(self.gst_percent), "gst_amount": float(self.gst_amount),
            "total_cost": float(self.total_cost),
            "bill_url": f"/uploads/materials/{self.bill_filename}" if self.bill_filename else None,
            "given_by_worker_id": self.given_by_worker_id, "given_by_name": self.given_by.name if self.given_by else None,
            "transport_mode": self.transport_mode, "transported_at": _iso(self.transported_at),
            "created_by_name": self.created_by.name if self.created_by else None,
            "created_at": _iso(self.created_at),
            "status": self.status,
            "approved_by_name": self.approved_by.name if self.approved_by else None,
            "approved_at": _iso(self.approved_at),
        }


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


class SiteCategory(_NamedOption):
    __tablename__ = "site_categories"


class SiteCategoryRequest(db.Model):
    """A site category someone typed in that isn't on the list yet. It only becomes a real category once the
    admin approves it on the Me tab; the admin can instead point it at an existing one, in which case every
    survey and client that used the typed name is changed to that one."""

    __tablename__ = "site_category_requests"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(60), nullable=False, index=True)
    requested_by_code = db.Column(db.String(4), db.ForeignKey("users.code", ondelete="SET NULL"), nullable=True)
    status = db.Column(db.String(12), nullable=False, default="pending", server_default="pending", index=True)
    target = db.Column(db.String(60), nullable=False, default="", server_default="")
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    requested_by = db.relationship("User")


class Module(db.Model):
    """A service listed in the sidebar (Leads, later attendance, manpower, ...). Edited in the database.
    in_nav=False is for a permission gate that isn't one of those tiles - Users & roles and Employee
    management live under their own "Manage" section on the Me hub instead (see _me_links.html), not mixed
    in with Clients/Projects/etc.; check_module still works on them exactly the same way."""

    __tablename__ = "modules"

    key = db.Column(db.String(30), primary_key=True)
    name = db.Column(db.String(60), nullable=False)
    icon = db.Column(db.String(30), nullable=False, default="grid", server_default="grid")
    path = db.Column(db.String(120), nullable=False)
    sort_order = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    is_active = db.Column(db.Boolean, nullable=False, default=True, server_default="1")
    admin_only = db.Column(db.Boolean, nullable=False, default=False, server_default="0")
    in_nav = db.Column(db.Boolean, nullable=False, default=True, server_default="1")


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
        "site_categories": SiteCategory.active_names(),
    }


class Attendance(db.Model):
    """One check-in/check-out session. Someone can check in and out more than once in a day (a lunch
    break, a second site) - so there can be more than one row per person per work_date, each one session;
    grouped back into a day's sessions for display (see app/attendance.py and the history view). At most
    one of a person's rows for a given day has no check_out_at yet - that's the session they're currently
    in, if any (see check_in below, which refuses a second one while one is still open). project_id is who
    they worked for that session and is optional, for office staff with no site to pick.

    Needs sign-off before it counts (kohal, 2026-10-16): the admin, Company Director, that project's
    manager, or a site supervisor currently checked into that exact project can approve it; office/marketing
    work (no project) needs the admin or Company Director specifically, since there's no project to approve
    against (see auth.can_approve_attendance). The check-in/check-out itself is never blocked by this -
    `status='pending'` only excludes a record from day/week counts and summaries until approved, same as a
    pending MaterialMovement is excluded from stock; see _recompute_material's sibling reasoning. Rejected,
    permanently, the same way. Every existing record, from before this existed, is 'approved'."""

    __tablename__ = "attendance"

    id = db.Column(db.Integer, primary_key=True)
    user_code = db.Column(db.String(4), db.ForeignKey("users.code", ondelete="CASCADE"), nullable=False, index=True)
    work_date = db.Column(db.Date, nullable=False, index=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True)
    check_in_at = db.Column(db.DateTime, nullable=False)
    check_in_lat = db.Column(db.Float, nullable=True)
    check_in_lng = db.Column(db.Float, nullable=True)
    check_out_at = db.Column(db.DateTime, nullable=True)
    notes = db.Column(db.String(400), nullable=False, default="", server_default="")
    # With no project: "" is office work, "marketing" is marketing work.
    work_kind = db.Column(db.String(20), nullable=False, default="", server_default="")
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    # Approval (see the class docstring) - pending | approved | rejected.
    status = db.Column(db.String(10), nullable=False, default="approved", server_default="approved")
    approved_by_code = db.Column(db.String(4), db.ForeignKey("users.code", ondelete="SET NULL"), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship("User", foreign_keys=[user_code])
    project = db.relationship("Project")
    approved_by = db.relationship("User", foreign_keys=[approved_by_code])

    @property
    def hours(self):
        if not self.check_out_at:
            return None
        return round((self.check_out_at - self.check_in_at).total_seconds() / 3600, 1)

    @property
    def check_in_map_url(self):
        if self.check_in_lat is None or self.check_in_lng is None:
            return None
        return f"https://maps.google.com/?q={self.check_in_lat},{self.check_in_lng}"

    def to_dict(self) -> dict:
        return {
            "id": self.id, "user_code": self.user_code, "user_name": self.user.name if self.user else None,
            "work_date": self.work_date.isoformat(), "project_id": self.project_id,
            "project_title": self.project.title if self.project else None,
            "project_code": self.project.code if self.project else None,
            "work_kind": self.work_kind,
            # What they were working on, in words: the project, or marketing / office work.
            "work_label": self.project.title if self.project else ("Marketing work" if self.work_kind == "marketing" else "Office work"),
            "check_in_at": _iso(self.check_in_at), "check_out_at": _iso(self.check_out_at),
            "check_in_lat": self.check_in_lat, "check_in_lng": self.check_in_lng,
            "check_in_map_url": self.check_in_map_url,
            "notes": self.notes, "hours": self.hours,
            "status": self.status,
            "approved_by_name": self.approved_by.name if self.approved_by else None,
            "approved_at": _iso(self.approved_at),
        }


class Worker(db.Model):
    """A field worker or office staff member who does not sign in to the app - tracked instead from the
    WhatsApp group they mark their attendance in. Separate from User: becomes a User only if ever given
    a login.
    category (manpower/staff) still decides who the Leads module offers as a surveyor or "enquired by"
    (see app/api.py - only "staff" shows up there) - that's a real, separate meaning from role_key, which
    is just the Employee management page's own grouping label, the same roles table Users & roles uses
    (minus 'admin'), and grants no sign-in or permission."""

    __tablename__ = "workers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    category = db.Column(db.String(20), nullable=False, default="manpower", server_default="manpower")   # manpower | staff
    role_key = db.Column(db.String(30), db.ForeignKey("roles.key"), nullable=True)
    source = db.Column(db.String(30), nullable=False, default="whatsapp", server_default="whatsapp")
    first_seen = db.Column(db.Date, nullable=True)
    last_seen = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    # The User (sign-in account) this row stands in for, if any - every non-admin User gets a matching
    # Worker row made for them automatically, once they've actually signed in for the first time (see
    # auth.sync_worker_for_user), so they show up wherever Workers do (Enquired by, surveyor...) without
    # being added twice. Not the other way around: plenty of Workers have no User at all.
    user_code = db.Column(db.String(4), db.ForeignKey("users.code", ondelete="SET NULL"), nullable=True, unique=True, index=True)

    # HR details - optional, filled in by the admin from Employee management; blank for anyone who's only
    # ever come in through the WhatsApp attendance import.
    age = db.Column(db.Integer, nullable=True)
    qualification = db.Column(db.String(160), nullable=False, default="", server_default="")
    experience = db.Column(db.String(200), nullable=False, default="", server_default="")
    skills = db.Column(db.String(400), nullable=False, default="", server_default="")
    phone = db.Column(EncryptedText, nullable=True)
    joining_date = db.Column(db.Date, nullable=True)
    employment_type = db.Column(db.String(20), nullable=False, default="", server_default="")   # regular | daily_wages
    wage_amount = db.Column(db.Numeric(14, 2), nullable=True)                  # salary (regular) or daily rate (daily_wages)
    pf_number = db.Column(EncryptedText, nullable=True)
    esic_number = db.Column(EncryptedText, nullable=True)
    reference = db.Column(db.String(200), nullable=False, default="", server_default="")

    role = db.relationship("Role")
    linked_user = db.relationship("User")
    attendance = db.relationship(
        "WorkerAttendance", back_populates="worker", cascade="all, delete-orphan",
        order_by="WorkerAttendance.work_date.desc()",
    )
    payments = db.relationship(
        "WorkerPayment", back_populates="worker", cascade="all, delete-orphan",
        order_by="WorkerPayment.position, WorkerPayment.id",
    )

    @property
    def paid_amount(self):
        """What's actually been paid - entries with a paid_date, not every entry in the log (a future/
        planned one can sit there unpaid)."""
        return sum((p.amount for p in self.payments if p.paid_date is not None), Decimal(0))

    def to_dict(self, detail: bool = False) -> dict:
        data = {
            "id": self.id, "name": self.name, "category": self.category, "source": self.source,
            "role_key": self.role_key, "role_name": self.role.name if self.role else None,
            "first_seen": self.first_seen.isoformat() if self.first_seen else None,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
        }
        if detail:
            data.update({
                "age": self.age, "qualification": self.qualification, "experience": self.experience,
                "skills": self.skills, "phone": self.phone,
                "joining_date": self.joining_date.isoformat() if self.joining_date else None,
                "employment_type": self.employment_type,
                "wage_amount": float(self.wage_amount) if self.wage_amount is not None else None,
                "pf_number": self.pf_number, "esic_number": self.esic_number, "reference": self.reference,
                "paid_amount": float(self.paid_amount),
                "payments": [p.to_dict() for p in self.payments],
            })
        return data


class WorkerAttendance(db.Model):
    """One day's attendance for a worker, read from the WhatsApp group's messages for that day: when they
    first messaged (check-in), and their last message that said "Exit" or similar (check-out), each with a
    location if one was shared right around that time. Someone else's message can be the source instead of
    the worker's own - a colleague saying "X is on leave" (status "absent") or naming X alongside their own
    present/exit message (X gets the same times and location) - see note for who actually said it.
    project_id is a best guess from the site name in that message, when one matched a project we know about.
    At most one row per worker per day."""

    __tablename__ = "worker_attendance"

    id = db.Column(db.Integer, primary_key=True)
    worker_id = db.Column(db.Integer, db.ForeignKey("workers.id", ondelete="CASCADE"), nullable=False, index=True)
    work_date = db.Column(db.Date, nullable=False, index=True)
    status = db.Column(db.String(10), nullable=False, default="present", server_default="present")   # present | absent
    check_in_at = db.Column(db.DateTime, nullable=True)
    check_in_lat = db.Column(db.Float, nullable=True)
    check_in_lng = db.Column(db.Float, nullable=True)
    check_out_at = db.Column(db.DateTime, nullable=True)
    check_out_lat = db.Column(db.Float, nullable=True)
    check_out_lng = db.Column(db.Float, nullable=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True)
    note = db.Column(db.String(300), nullable=False, default="", server_default="")
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    worker = db.relationship("Worker", back_populates="attendance")
    project = db.relationship("Project")

    __table_args__ = (db.UniqueConstraint("worker_id", "work_date", name="uq_worker_attendance_worker_date"),)

    @property
    def hours(self):
        if not self.check_in_at or not self.check_out_at:
            return None
        return round((self.check_out_at - self.check_in_at).total_seconds() / 3600, 1)

    @staticmethod
    def _map_url(lat, lng):
        return f"https://maps.google.com/?q={lat},{lng}" if lat is not None and lng is not None else None

    def to_dict(self) -> dict:
        return {
            "id": self.id, "worker_id": self.worker_id, "work_date": self.work_date.isoformat(),
            "status": self.status,
            "check_in_at": _iso(self.check_in_at), "check_out_at": _iso(self.check_out_at),
            "check_in_map_url": self._map_url(self.check_in_lat, self.check_in_lng),
            "check_out_map_url": self._map_url(self.check_out_lat, self.check_out_lng),
            "project_id": self.project_id, "project_title": self.project.title if self.project else None,
            "project_code": self.project.code if self.project else None,
            "note": self.note, "hours": self.hours,
        }


class WorkerPayment(db.Model):
    """One entry in a worker's salary/wages log - the same shape as ProjectPayment, just not tied to a
    milestone: usually one entry per pay period (a month's salary, a week's daily wages, ...)."""

    __tablename__ = "worker_payments"

    id = db.Column(db.Integer, primary_key=True)
    worker_id = db.Column(db.Integer, db.ForeignKey("workers.id", ondelete="CASCADE"), nullable=False, index=True)
    label = db.Column(db.String(120), nullable=False)
    amount = db.Column(db.Numeric(14, 2), nullable=False, default=0, server_default="0")
    due_date = db.Column(db.Date, nullable=True)
    position = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    mode = db.Column(db.String(40), nullable=False, default="", server_default="")
    paid_date = db.Column(db.Date, nullable=True)
    comments = db.Column(db.Text, nullable=False, default="", server_default="")

    worker = db.relationship("Worker", back_populates="payments")

    def to_dict(self) -> dict:
        return {
            "label": self.label, "amount": float(self.amount),
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "mode": self.mode,
            "paid_date": self.paid_date.isoformat() if self.paid_date else None,
            "comments": self.comments,
        }
