"""Put back what a bad migration wiped, from a pre-deploy backup - insert-only, never overwrites.

A migration that rebuilt `users` with SQLite foreign keys on (fixed in migrations/env.py, 2026-10-26) fired
every child table's ON DELETE rule: attendance, absence requests, announcement recipients and state
assignments were deleted (CASCADE), and every "who owns / created / approved this" column was blanked (SET
NULL). This brings both back from a backup taken just before that deploy.

Strict rules (kohal, 2026-10-26 - production history is never overwritten or deleted):
  * only INSERTs rows the live database does not already have (matched by their natural key, never by id -
    the live ids restarted from 1 after the wipe), and only UPDATEs a column that is currently NULL;
  * no DELETE, no DROP, nothing already filled in is changed;
  * dry run by default - prints exactly what it would do and rolls everything back. --apply to keep it.

Usage (on a COPY first, then on the live file once the dry run and the copy both look right):
    python scripts/restore_from_backup.py --backup ~/safe-backups/leads-20261023-040126.db --target /path/to/copy.db
    python scripts/restore_from_backup.py --backup ... --target ... --apply
"""

import argparse
import sqlite3
import sys

# (table, natural key columns) - rows are matched on these, and inserted without their old id.
CASCADED = [
    ("attendance", ("user_code", "check_in_at")),
    ("absence_requests", ("user_code", "for_date")),
    ("announcement_recipients", ("announcement_id", "user_code")),
    ("user_states", ("user_code", "state")),
]


def columns(conn, schema, table):
    return [r[1] for r in conn.execute(f"pragma {schema}.table_info({table})")]


def restore_cascaded(conn, table, key):
    live, old = columns(conn, "main", table), columns(conn, "bk", table)
    cols = [c for c in live if c in old and c != "id"]
    missing_required = [r[1] for r in conn.execute(f"pragma main.table_info({table})")
                        if r[1] not in old and r[3] and r[4] is None and not r[5]]
    if missing_required:
        raise SystemExit(f"{table}: live table needs {missing_required}, which the backup does not have - stopping.")
    select = []
    for c in cols:
        if c == "project_id":      # a project deleted since must not make the row un-insertable
            select.append("CASE WHEN b.project_id IN (SELECT id FROM main.projects) THEN b.project_id END")
        elif c in ("approved_by_code", "decided_by_code"):
            select.append(f"CASE WHEN b.{c} IN (SELECT code FROM main.users) THEN b.{c} END")
        else:
            select.append(f"b.{c}")
    same = " AND ".join(f"l.{k} IS b.{k}" for k in key)
    sql = (f"INSERT INTO main.{table} ({', '.join(cols)}) SELECT {', '.join(select)} FROM bk.{table} b "
           f"WHERE b.user_code IN (SELECT code FROM main.users) "
           f"AND NOT EXISTS (SELECT 1 FROM main.{table} l WHERE {same})")
    return conn.execute(sql).rowcount


def blanked_columns(conn):
    """Every (table, column) in the live database that points at users.code with ON DELETE SET NULL."""
    out = []
    for (table,) in conn.execute("select name from main.sqlite_master where type='table' and name not like 'sqlite_%'").fetchall():
        for fk in conn.execute(f"pragma main.foreign_key_list({table})").fetchall():
            if fk[2] == "users" and fk[6] == "SET NULL":
                out.append((table, fk[3]))
    return out


def refill_nulls(conn, table, col):
    if "id" not in columns(conn, "main", table) or "id" not in columns(conn, "bk", table):
        return None
    if col not in columns(conn, "bk", table):
        return None
    # A worker's login link is unique: skip it if that user has already been linked to another worker.
    extra = (f" AND NOT EXISTS (SELECT 1 FROM main.{table} o WHERE o.{col} = b.{col})" if table == "workers" else "")
    sql = (f"UPDATE main.{table} SET {col} = (SELECT b.{col} FROM bk.{table} b WHERE b.id = main.{table}.id) "
           f"WHERE {col} IS NULL AND EXISTS (SELECT 1 FROM bk.{table} b WHERE b.id = main.{table}.id "
           f"AND b.{col} IS NOT NULL AND b.{col} IN (SELECT code FROM main.users){extra})")
    return conn.execute(sql).rowcount


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backup", required=True, help="the pre-deploy backup to restore FROM (opened read-only)")
    ap.add_argument("--target", required=True, help="the database to restore INTO (a copy first!)")
    ap.add_argument("--apply", action="store_true", help="keep the changes; without it everything is rolled back")
    args = ap.parse_args()

    conn = sqlite3.connect(f"file:{args.target.replace(chr(92), '/')}?mode=rw", uri=True, isolation_level=None)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("ATTACH DATABASE ? AS bk", (f"file:{args.backup.replace(chr(92), '/')}?mode=ro",))
    conn.execute("BEGIN")
    try:
        print("Rows put back (inserted, because the live database does not have them):")
        for table, key in CASCADED:
            before = conn.execute(f"select count(*) from main.{table}").fetchone()[0]
            added = restore_cascaded(conn, table, key)
            print(f"  {table:25} live had {before:5}, +{added}")
        print("Blanked 'who did this' columns refilled (only where currently empty):")
        for table, col in blanked_columns(conn):
            # The tables above were emptied, so their live ids restarted from 1 and no longer line up with the
            # backup's - matching on id would copy the wrong person onto a row. Their own columns already
            # came across with the insert above.
            if table in {t for t, _ in CASCADED}:
                continue
            n = refill_nulls(conn, table, col)
            if n:
                print(f"  {table}.{col:20} {n}")
        bad = conn.execute("pragma foreign_key_check").fetchall()
        if bad:
            raise SystemExit(f"foreign key problems after restore, rolled back: {bad[:5]}")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    if args.apply:
        conn.execute("COMMIT")
        print("APPLIED.")
    else:
        conn.execute("ROLLBACK")
        print("Dry run only - nothing was changed. Add --apply to keep these.")


if __name__ == "__main__":
    sys.exit(main())
