# Data integrity: relationships, constraints and migrations

This is the reference for how the database links its records, what it refuses, and how to migrate it safely. The schema is defined by migrations in `backend/migrations/versions/`. The current head is `0007_relational_integrity`.

## Relationships

| Record | Links to | Enforced by | On parent delete |
|---|---|---|---|
| Draft (`email_drafts`) | Restaurant (required), campaign (optional, by name for old drafts) | Foreign keys | RESTRICT |
| Campaign recipient (`campaign_recipients`) | Campaign (required), restaurant (required), draft (optional) | Foreign keys; one row per campaign and restaurant (unique) | RESTRICT |
| Email ledger (`email_send_ledger`) | Campaign, recipient (as a pair), restaurant, draft | Foreign keys, including the composite pair (campaign, recipient), so a ledger row can't point at another campaign's recipient | RESTRICT |
| Delivery event (`email_events`) | Recipient and campaign (both optional, as a matching pair) | Foreign keys, including the composite pair | RESTRICT |
| Reply (`email_conversations`) | Restaurant, recipient and campaign (optional, as a matching pair) | Foreign keys, including the composite pair | RESTRICT |
| Send log (`campaign_send_logs`) | Campaign (required), recipient, restaurant (both optional) | Foreign keys | Campaign: RESTRICT. Recipient and restaurant: SET NULL, so the log line keeps its text |
| Suppression (`suppression_list`) | Email address (no table link, by design: an address can be suppressed before it is ever a recipient) | Primary key | Not applicable |
| Sign-in session (`auth_sessions`) | None | Primary key | Not applicable |
| Mailbox cursor (`email_sync_state`) | None | Primary key | Not applicable |

There is no `users` table. The application has one shared admin password and no user accounts, so there is nothing to link to.

## Deletion policy

- **RESTRICT** protects every link that carries sending or reply history. A restaurant, campaign, draft or recipient that has history cannot be deleted by accident. The database refuses the delete, and the history stays intact.
- **SET NULL** is used only on send logs, because the log keeps the recipient's address and event as text.
- The application has no endpoint that deletes business records. The only deletions are of expired sign-in sessions. Soft deletion is not needed today. If a restaurant ever has to be removed, it must first be archived, and the history must stay where it is.

## Constraints added by migration 0007

- **Foreign keys** on every link in the table above, and composite foreign keys so that a ledger row, delivery event or reply can only point at a recipient of its own campaign.
- **Unique**: recipients by (campaign, id), which the composite keys need.
- **Check constraints** on status columns, limited to the values the application writes:
  - campaigns: generating, review, sending, paused, completed, cancelled
  - recipients: drafting, draft_failed, draft, skipped, queued, sending, sent, failed, interrupted, cancelled; delivery status: none, or delivered, deferred, bounced_soft, bounced_hard, rejected
  - drafts: draft, approved, rejected
  - ledger: reserved, sent, failed, uncertain, bounced; attempts at least 1
  - events: delivered, deferred, bounced_soft, bounced_hard, rejected
  - replies: matched, needs_review, unmatched, dismissed; direction inbound
  - restaurants: lead status, contact email status and classification (or none); opted out is 0 or 1

Existing unique constraints are unchanged: place ID, (campaign, restaurant) for recipients, one active draft per restaurant and campaign name, one ledger row per recipient, event keys, message keys, and suppression addresses.

## Indexes added

Indexes on the link columns that were missing them: recipients by restaurant and by draft; ledger by restaurant and by draft; events by campaign; replies by campaign and by restaurant; send logs by recipient and by restaurant; drafts by campaign.

## Audit before migrating

The migration refuses to run while the data breaks a rule. It changes nothing and deletes nothing. The audit checks:

- every link points at an existing parent;
- a ledger row, event or reply points at a recipient of its own campaign;
- a recipient's draft belongs to the same restaurant;
- no duplicate active drafts, recipients, ledger rows or place IDs;
- no status value outside the lists above;
- suppression addresses are stored in lower case (reported by count only, so no address is printed).

Run it on the database you are about to migrate:

```powershell
cd backend
python scripts\audit_integrity.py
```

Exit code 0 means the data is clean. Exit code 1 lists each problem with a count and sample IDs. Fix each row by hand: correct the link, clear an optional link, or export the row (`scripts/logical_backup.py`) and remove it deliberately. Nothing is removed automatically.

## Backup before migrating

Always take a backup first. A backup never changes the schema.

```powershell
cd backend
python scripts\logical_backup.py export --database-url "postgresql+psycopg://USER:PASSWORD@HOST:5432/DBNAME" --out "..\backups\before-0007"
```

For a local SQLite file, stop the backend and copy the file to a dated name. Keep the copy until the migrated data has been checked.

Note: the running development server applies pending migrations when it reloads. Stop it before migrating, or the migration can run before your backup is taken.

## Migrating

```powershell
cd backend
alembic upgrade head
```

On SQLite, tables are rebuilt (copied and swapped) because SQLite cannot add constraints to an existing table. Foreign keys are switched off during the rebuild and checked afterwards; if any violation is found, the migration reports it. On PostgreSQL the constraints are added in place.

## Rolling back

```powershell
cd backend
alembic downgrade 0006_email_events_and_replies
```

The downgrade removes exactly the constraints and indexes that migration 0007 added. The data is unchanged. Running `alembic upgrade head` again restores them.

## Foreign keys on SQLite

SQLite ignores foreign keys unless each connection enables them. The application enables them every time a connection is taken from the pool, so this holds for every query, not only the first one.

## Known gaps (not changed in this phase)

- `campaigns.approved_draft_ids` is a JSON list of draft IDs in a text column, so the database cannot check it.
- `email_drafts.campaign` is the campaign name as text, kept for drafts made before campaigns existed. The link that matters is `campaign_id`.
- `suppression_list` is keyed by address, not by restaurant or recipient, by design.
- The `leads` table from the first migration is not used by the application. It is left alone and can be dropped in a later cleanup, after a backup.
- SQLite migrations are slower, because each table is rebuilt. This makes each fresh test database take longer to set up.
