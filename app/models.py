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
    (name-1234). PINs and setup codes are stored only as hashes."""

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
    role_key = db.Column(db.String(30), db.ForeignKey("roles.key"), nullable=True)

    role = db.relationship("Role")

    @property
    def sees_all(self) -> bool:
        """The admin, and any role marked sees_all (for example Accounts), see every client and project."""
        return bool(self.is_admin or (self.role and self.role.sees_all))

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
    site_category = db.Column(db.String(60), nullable=False, default="", server_default="")
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
    checklist = db.relationship(
        "ChecklistItem",
        back_populates="lead",
        cascade="all, delete-orphan",
        order_by="ChecklistItem.position, ChecklistItem.id",
    )
    project = db.relationship("Project", back_populates="lead", uselist=False)

    def to_dict(self, with_activities: bool = False) -> dict:
        data = {
            "id": self.id,
            "contact_name": self.contact_name,
            "company": self.company,
            "phone": self.phone,
            "email": self.email,
            "site_category": self.site_category,
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
            "project_id": self.project.id if self.project else None,
        }
        if with_activities:
            data["activities"] = [a.to_dict() for a in self.activities]
            data["checklist"] = [c.to_dict() for c in self.checklist]
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


class ChecklistItem(db.Model):
    """One tick-off item on a lead's work checklist."""

    __tablename__ = "lead_checklist_items"

    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)
    text = db.Column(db.String(200), nullable=False)
    done = db.Column(db.Boolean, nullable=False, default=False, server_default="0")
    position = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    lead = db.relationship("Lead", back_populates="checklist")

    def to_dict(self) -> dict:
        return {"id": self.id, "text": self.text, "done": self.done}


class Role(db.Model):
    """What a kind of user is called and whether they see every client and project. Edited in the database."""

    __tablename__ = "roles"

    key = db.Column(db.String(30), primary_key=True)
    name = db.Column(db.String(60), nullable=False)
    sees_all = db.Column(db.Boolean, nullable=False, default=False, server_default="0")


class RoleModule(db.Model):
    """Which services a role can open (the admin can open all of them)."""

    __tablename__ = "role_modules"

    role_key = db.Column(db.String(30), db.ForeignKey("roles.key", ondelete="CASCADE"), primary_key=True)
    module_key = db.Column(db.String(30), db.ForeignKey("modules.key", ondelete="CASCADE"), primary_key=True)


class Client(db.Model):
    """A customer. Created from a won lead (or added by hand) and kept for every project done for them."""

    __tablename__ = "clients"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    contact_name = db.Column(db.String(120), nullable=False, default="", server_default="")
    phone = db.Column(db.String(40), nullable=False, default="", server_default="")
    email = db.Column(db.String(160), nullable=False, default="", server_default="")
    site_category = db.Column(db.String(60), nullable=False, default="", server_default="")
    pincode = db.Column(db.String(6), nullable=False, default="", server_default="")
    state = db.Column(db.String(80), nullable=False, default="", server_default="")
    district = db.Column(db.String(80), nullable=False, default="", server_default="")
    city = db.Column(db.String(120), nullable=False, default="", server_default="")
    address = db.Column(db.String(400), nullable=False, default="", server_default="")
    notes = db.Column(db.Text, nullable=False, default="", server_default="")
    owner_code = db.Column(db.String(4), db.ForeignKey("users.code", ondelete="SET NULL"), nullable=True, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    owner = db.relationship("User")
    projects = db.relationship("Project", back_populates="client", order_by="Project.id.desc()")

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "contact_name": self.contact_name, "phone": self.phone,
            "email": self.email, "site_category": self.site_category, "pincode": self.pincode,
            "state": self.state, "district": self.district, "city": self.city, "address": self.address,
            "notes": self.notes, "owner_name": self.owner.name if self.owner else None,
            "project_count": len(self.projects),
        }


class Project(db.Model):
    """A piece of work for a client, usually created when a lead is won."""

    __tablename__ = "projects"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=False, index=True)
    lead_id = db.Column(db.Integer, db.ForeignKey("leads.id", ondelete="SET NULL"), nullable=True, unique=True)
    title = db.Column(db.String(160), nullable=False)
    work_category = db.Column(db.String(120), nullable=False, default="", server_default="")
    status = db.Column(db.String(20), nullable=False, default="planned", server_default="planned", index=True)
    site_pincode = db.Column(db.String(6), nullable=False, default="", server_default="")
    site_state = db.Column(db.String(80), nullable=False, default="", server_default="")
    site_district = db.Column(db.String(80), nullable=False, default="", server_default="")
    site_city = db.Column(db.String(120), nullable=False, default="", server_default="")
    site_address = db.Column(db.String(400), nullable=False, default="", server_default="")
    work_order_no = db.Column(db.String(60), nullable=False, default="", server_default="")
    work_order_date = db.Column(db.Date, nullable=True)
    start_date = db.Column(db.Date, nullable=True)
    completion_days = db.Column(db.Integer, nullable=True)
    estimated_amount = db.Column(db.Numeric(14, 2), nullable=True)
    discount_amount = db.Column(db.Numeric(14, 2), nullable=False, default=0, server_default="0")
    payment_terms = db.Column(db.Text, nullable=False, default="", server_default="")
    special_terms = db.Column(db.Text, nullable=False, default="", server_default="")
    manager_code = db.Column(db.String(4), db.ForeignKey("users.code", ondelete="SET NULL"), nullable=True, index=True)
    owner_code = db.Column(db.String(4), db.ForeignKey("users.code", ondelete="SET NULL"), nullable=True, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    client = db.relationship("Client", back_populates="projects")
    lead = db.relationship("Lead", back_populates="project")
    manager = db.relationship("User", foreign_keys=[manager_code])
    owner = db.relationship("User", foreign_keys=[owner_code])
    payments = db.relationship(
        "ProjectPayment", back_populates="project", cascade="all, delete-orphan",
        order_by="ProjectPayment.position, ProjectPayment.id",
    )

    @property
    def code(self) -> str:
        return f"PRJ-{self.id:04d}"

    @property
    def net_amount(self):
        if self.estimated_amount is None:
            return None
        return self.estimated_amount - (self.discount_amount or 0)

    def to_dict(self, detail: bool = False) -> dict:
        def num(v):
            return float(v) if v is not None else None

        data = {
            "id": self.id, "code": self.code, "title": self.title, "status": self.status,
            "work_category": self.work_category, "client_id": self.client_id, "client_name": self.client.name,
            "estimated_amount": num(self.estimated_amount), "discount_amount": num(self.discount_amount),
            "net_amount": num(self.net_amount), "manager_code": self.manager_code,
            "manager_name": self.manager.name if self.manager else None,
            "lead_id": self.lead_id,
        }
        if detail:
            data.update({
                "site_pincode": self.site_pincode, "site_state": self.site_state,
                "site_district": self.site_district, "site_city": self.site_city, "site_address": self.site_address,
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

    project = db.relationship("Project", back_populates="payments")

    def to_dict(self) -> dict:
        return {
            "label": self.label, "amount": float(self.amount),
            "due_date": self.due_date.isoformat() if self.due_date else None,
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


class Module(db.Model):
    """A service listed in the sidebar (Leads, later attendance, manpower, ...). Edited in the database."""

    __tablename__ = "modules"

    key = db.Column(db.String(30), primary_key=True)
    name = db.Column(db.String(60), nullable=False)
    icon = db.Column(db.String(30), nullable=False, default="grid", server_default="grid")
    path = db.Column(db.String(120), nullable=False)
    sort_order = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    is_active = db.Column(db.Boolean, nullable=False, default=True, server_default="1")
    admin_only = db.Column(db.Boolean, nullable=False, default=False, server_default="0")


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
