from __future__ import annotations

SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notes_sort ON notes(sort_order, created_at);
"""


async def startup(ctx) -> None:
    async with ctx.storage.connect() as db:
        await db.executescript(SCHEMA)
        await db.commit()
