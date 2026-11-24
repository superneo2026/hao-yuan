---
name: sqlite-migration
title: SQLite Migration and Idempotency
description: Checklist for moving existing data into SQLite with unique constraints, foreign keys, transactions and safe re-runs.
kinds: dev
triggers: sqlite,sqlite3,migration,migrate,schema,unique,foreign key,rollback,idempotent,transaction,迁移,幂等,唯一,外键,回滚,事务
version: 1.0.0
---

## Inspect before migrating
- Inventory the source data and the target schema: row counts, column types, nulls, duplicates, and any rows that violate the intended constraints.
- Run the migration against a copy or a temporary database first. Never debug on the only copy of the data.

## Constraints
- Unique: detect and resolve duplicates before creating a unique index. Choose an explicit conflict policy (fail, ignore, or update) and make it visible in the result.
- Foreign keys: enable `PRAGMA foreign_keys=ON`, insert parents before children, and decide delete/update behavior (restrict, cascade, or set null) explicitly.
- Not-null/default: fill or reject bad rows before the constraint is added; do not rely on silent coercion.

## Transactions and rollback
- Wrap schema changes and data movement in a transaction so a failure leaves the database unchanged.
- Test the failure path: inject a bad row or a constraint violation and confirm rollback.
- Keep DDL and DML ordering deterministic; avoid partial visibility between steps.

## Idempotent re-runs
- The migration must be idempotent and safe to run twice: use `IF NOT EXISTS`, `ON CONFLICT`, a migration-version marker, or an equivalent guard.
- Re-running must not duplicate rows, reset data, or fail on an already-migrated database.
- Record the applied version only after the transaction commits.

## Verification
- Migrate an empty database, a populated database, and a database that was already migrated.
- Compare row counts, unique constraints, and foreign-key relationships after each run.
- Run `PRAGMA integrity_check` and `PRAGMA foreign_key_check`; confirm both are clean.
- Verify a second run produces the same final state and exits successfully.
