"""Guardrail (kohal, 2026-10-26, STRICT): a migration must never delete or overwrite production data.

A migration once rebuilt `users` with foreign keys on and silently wiped a month of attendance on the live site.
This fails the suite for any NEW migration whose upgrade() deletes, drops, truncates or rebuilds a table in
place - the only way to make such a change is for kohal to approve that specific migration (asked twice, with
the reason explained) and for the file to carry the marker `# prod-data-change-approved: <why>` in upgrade().
The migrations that already exist are grandfathered below; do not add to that list.
"""

import ast
import re
from pathlib import Path

VERSIONS = Path(__file__).resolve().parent.parent / "migrations" / "versions"

GRANDFATHERED = {
    "0a713797f60c_site_categories_and_requests.py",
    "0ba43da7795f_sub_admin_role_and_states.py",
    "30f0f4d3a002_survey_site_name.py",
    "5dcbdf70f991_project_final_amount.py",
    "6d5c22cb4c46_project_site_name.py",
    "a139ace11c38_initial_schema.py",
    "a1c7e4f9b230_merge_duplicate_worker_from_user.py",
    "a2c7f1e9b543_project_documents.py",
    "a3c7e1f5b928_project_completed_at.py",
    "a3c7e1f9d548_fooding_opt_in_backfill.py",
    "a3c7e9f1b026_worker_category.py",
    "a3c7f1e9b204_worker_role_key.py",
    "a7e3c9f2b584_attendance_approval.py",
    "a8d4f1c6e932_roles_clients_projects.py",
    "a8d4f2c6e9b1_lead_work_order_advance.py",
    "a8e5d3b7f204_rename_workplan_module.py",
    "a93c5d7e2f14_project_stage_remarks.py",
    "b2c5f7a913de_inventory_gst_and_suppliers.py",
    "b3e7c1a9f452_drop_lead_checklist.py",
    "b58e2d4a917c_employee_details_and_payments.py",
    "b5f9d3a7c642_material_movement_transport.py",
    "b6e2d9f4a171_trade_roles_and_accountant.py",
    "b6e4d928a3f7_project_stage_payment.py",
    "b7c2e4a91d05_rename_lead_desk_to_leads.py",
    "b7c4d2e6f891_absence_requests.py",
    "b7e2f9a4c816_attendance_rejection_seen_at.py",
    "b8f3a1d6c925_cash_requests.py",
    "b9c253a2584b_payment_mode_and_comments.py",
    "b9d4c2a71e03_multi_session_attendance.py",
    "c1d5f8a3b6e2_attendance.py",
    "c2a8f5e713d9_site_trade_daily_wage_backfill.py",
    "c2d8f4a9e136_lead_pipeline_rework.py",
    "c3f6b1d8e4a7_role_based_access.py",
    "c3f8a1b25d7e_lookup_tables.py",
    "c4a1d7e3f958_inventory.py",
    "c7f3a9e2d514_attendance_work_kind.py",
    "c8e3b1f6a729_project_expenses.py",
    "c9a1e5f7b283_user_phone.py",
    "c9d3e7f1a254_work_assignments.py",
    "d2e9c4b7f105_attendance_location.py",
    "d2f8a4c6e913_material_movements_requested.py",
    "d41c8f93a7b0_project_stages.py",
    "d4a6e8c2f731_worker_payments_period_start.py",
    "d4e9b7c0a1f3_site_location.py",
    "d4f7c2a9b813_fooding.py",
    "d7f2a4b891c3_stock_in_seller_and_bill.py",
    "d7f3a1c9b284_lead_enquired_by.py",
    "d8f1a6c93b57_material_units.py",
    "d9b4e6f2a831_site_details_to_survey.py",
    "e2b4a8c17f93_material_frequency_and_used_in.py",
    "e4f8a2c6d913_workers.py",
    "e5a1c8d2b6f4_users_and_owners.py",
    "e5a9c3f7b162_client_role_and_login.py",
    "e7a4c9f2b816_worker_user_code_link.py",
    "e9b4f8d2c637_fooding_entries.py",
    "eff82647a228_more_services.py",
    "f1a6d8e4b259_fooding_opt_in.py",
    "f3a7c9e2d615_announcements.py",
    "f3d81a6c5e92_drop_manual_employees_resync.py",
    "f4c8a2e6d931_material_movement_approval.py",
    "f6b2d9e13a70_modules.py",
    "f7b2e4a918c6_project_stage_pause.py",
    "f7b3d5e2a084_worker_attendance_status_project.py",
    "fe3d625d936b_cash_purchases.py",
}

FORBIDDEN = re.compile(
    r"DELETE\s+FROM|DROP\s+TABLE|TRUNCATE|drop_table|drop_column|drop_constraint|batch_alter_table|"
    r"UPDATE\s+\w+\s+SET|executescript",
    re.IGNORECASE,
)
APPROVED = "prod-data-change-approved:"


def upgrade_source(path):
    text = path.read_text(encoding="utf-8")
    for node in ast.parse(text).body:
        if isinstance(node, ast.FunctionDef) and node.name == "upgrade":
            return ast.get_source_segment(text, node) or ""
    return ""


def test_new_migrations_never_delete_or_rewrite_existing_data():
    problems = []
    for path in sorted(VERSIONS.glob("*.py")):
        if path.name in GRANDFATHERED:
            continue
        src = upgrade_source(path)
        if APPROVED in src:
            continue
        for match in FORBIDDEN.finditer(src):
            problems.append(f"{path.name}: upgrade() uses {match.group(0)!r}")
    assert not problems, (
        "A new migration can delete or overwrite production data - not allowed without kohal's explicit, "
        "twice-confirmed approval (see this file's docstring):\n  " + "\n  ".join(problems)
    )


def test_grandfathered_list_only_names_real_files():
    missing = [n for n in GRANDFATHERED if not (VERSIONS / n).exists()]
    assert not missing, f"stale entries in GRANDFATHERED: {missing}"
