from datetime import timedelta

import click

from .extensions import db
from .auth import create_user, find_user, issue_setup_code, SETUP_CODE_DAYS
from .models import Activity, Lead, User, utcnow
from .timeutil import today_local

# (company, contact, phone, service, source, value, stage, follow-up offset in days or None, notes)
DEMO = [
    ("Kalyani Cold Storage", "R. Kulkarni", "9800000001", "Sprinklers", "Referral", 1850000, "New enquiry", 0, "Wants ESFR sprinklers for a new 40,000 sq ft chamber."),
    ("Orchid Heights CHS", "Mrs. Deshpande", "9800000002", "Fire alarms", "Walk-in", 420000, "New enquiry", 2, "Society committee meets on Sunday."),
    ("Neelkanth Plastics", "S. Patil", "9800000003", "Extinguishers", "Cold call", 95000, "New enquiry", None, ""),
    ("Sahyadri Diagnostics", "Dr. Bhosale", "9800000004", "NOC and audits", "Consultant / architect", 160000, "Site survey", -2, "Survey done on the ground floor. Basement pending."),
    ("Ambika Auto Components", "P. Jadhav", "9800000005", "Hydrant and pump room", "Tender / RFQ", 3200000, "Site survey", 3, "Tender closes end of the month."),
    ("Greenfield Warehousing", "A. Shaikh", "9800000006", "Sprinklers", "Website", 2750000, "Quote sent", -5, "Quote sent by email. No reply yet."),
    ("Vaidya Hospital", "Admin office", "9800000007", "Gas suppression", "Referral", 1240000, "Quote sent", 1, "Server room and records room."),
    ("Mahalaxmi Mall", "Facility head", "9800000008", "AMC", "Repeat client", 680000, "Negotiation", 0, "Asked for 10% off on a 2-year AMC."),
    ("Suyog Engineering", "M. Gaikwad", "9800000009", "Fire alarms", "Referral", 540000, "Negotiation", 6, ""),
    ("Riverside Homes", "Builder's office", "9800000010", "Hydrant and pump room", "Consultant / architect", 2100000, "Won", None, "Order received. Site start next month."),
    ("Pinnacle IT Park", "Facility team", "9800000011", "AMC", "Repeat client", 890000, "Won", None, ""),
    ("Omkar Foods", "V. More", "9800000012", "Extinguishers", "Cold call", 70000, "Lost", None, "Went with a local dealer on price."),
]


def _print_credentials(user, setup_code):
    click.echo("")
    click.echo(f"  Userid:      {user.userid}")
    click.echo(f"  Setup code:  {setup_code}   (one time, valid for {SETUP_CODE_DAYS} days)")
    click.echo("")
    click.echo("Open /set-password in the app, enter the userid and setup code, then choose a password.")
    click.echo("The setup code is not stored anywhere readable, so copy it now.")


def register_cli(app):
    @app.cli.command("create-admin")
    @click.option("--name", default="grtechno", show_default=True, help="Name for the admin account.")
    @click.option("--code", default=None, help="Choose the 4-digit code (userid is name-code). Random if left out.")
    def create_admin(name, code):
        """Create the one admin account and print its userid and setup code."""
        existing = User.query.filter_by(is_admin=True).first()
        if existing:
            raise click.ClickException(
                f"An admin already exists ({existing.userid}). To give it a new setup code run: "
                f"flask --app wsgi reset-password {existing.userid}"
            )
        try:
            user, setup_code = create_user(name, is_admin=True, code=code)
        except ValueError as err:
            raise click.ClickException(str(err))
        db.session.commit()
        click.echo("Admin created.")
        _print_credentials(user, setup_code)

    @app.cli.command("reset-password")
    @click.argument("userid")
    def reset_password(userid):
        """Switch off a user's password and print a new setup code (use this if the admin forgets theirs)."""
        user = find_user(userid)
        if user is None:
            raise click.ClickException(f"No user with the userid {userid!r}.")
        setup_code = issue_setup_code(user)
        db.session.commit()
        click.echo(f"New setup code issued for {user.name}.")
        _print_credentials(user, setup_code)

    @app.cli.command("seed-demo")
    @click.option("--force", is_flag=True, help="Delete every existing lead first.")
    def seed_demo(force):
        """Fill the database with sample leads so you can try the app."""
        if Lead.query.count() and not force:
            raise click.ClickException("Leads already exist. Use --force to replace them.")
        if force:
            # Children first: a bulk delete bypasses the ORM cascade.
            Activity.query.delete()
            Lead.query.delete()
            db.session.commit()

        owner = User.query.filter_by(is_admin=True).first()
        today = today_local()
        for company, contact, phone, service, source, value, stage, offset, notes in DEMO:
            lead = Lead(
                company=company,
                contact_name=contact,
                phone=phone,
                email=f"info@{company.split()[0].lower()}.example.com",
                site_pincode="411001",
                site_state="Maharashtra",
                site_district="Pune",
                site_city="Pune City",
                site_address="Pune, Maharashtra",
                service=service,
                source=source,
                est_value=value,
                stage=stage,
                follow_up_date=today + timedelta(days=offset) if offset is not None else None,
                notes=notes,
                closed_at=utcnow() if stage in ("Won", "Lost") else None,
                owner_code=owner.code if owner else None,
            )
            lead.activities.append(Activity(kind="created", text="Lead created"))
            db.session.add(lead)
        db.session.commit()
        click.echo(f"Added {len(DEMO)} demo leads.")
