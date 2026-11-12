from __future__ import annotations

from math import ceil
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from configs.configs import prefix
from core.harness import harness_instance
from core.storage import new_id, now

router = APIRouter(prefix=prefix, tags=["notes"])

DEFAULT_PAGE_SIZE = 8
MAX_PAGE_SIZE = 50
MAX_TITLE = 200
MAX_CONTENT = 40000
UNTITLED = "无标题笔记"


class NoteBody(BaseModel):
    title: str = ""
    content: str = ""


class ReorderBody(BaseModel):
    note_id: str
    target_index: int


def _row(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "content": row["content"],
        "sort_order": row["sort_order"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _clean_title(value: str) -> str:
    return str(value or "").strip()[:MAX_TITLE] or UNTITLED


def _clean_content(value: str) -> str:
    return str(value or "")[:MAX_CONTENT]


async def _fetch_note(note_id: str) -> dict[str, Any] | None:
    storage = harness_instance().storage
    async with storage.connect() as db:
        async with db.execute("SELECT * FROM notes WHERE id=?", (note_id,)) as cursor:
            row = await cursor.fetchone()
    return _row(row) if row else None


@router.get("/notes")
async def list_notes(page: int = 1, page_size: int = DEFAULT_PAGE_SIZE, q: str = ""):
    page_size = max(1, min(MAX_PAGE_SIZE, int(page_size or DEFAULT_PAGE_SIZE)))
    page = max(1, int(page or 1))
    query = str(q or "").strip()
    where = ""
    params: list[Any] = []
    if query:
        like = f"%{query}%"
        where = "WHERE title LIKE ? OR content LIKE ?"
        params = [like, like]

    storage = harness_instance().storage
    async with storage.connect() as db:
        async with db.execute(f"SELECT COUNT(*) AS total FROM notes {where}", tuple(params)) as cursor:
            count_row = await cursor.fetchone()
        total = int(count_row["total"] if count_row else 0)
        pages = max(1, ceil(total / page_size)) if total else 1
        page = min(page, pages)
        offset = (page - 1) * page_size
        async with db.execute(
            f"SELECT * FROM notes {where} ORDER BY sort_order ASC, created_at ASC, id ASC LIMIT ? OFFSET ?",
            (*params, page_size, offset),
        ) as cursor:
            rows = await cursor.fetchall()

    return {
        "code": 200,
        "data": {
            "items": [_row(row) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": pages,
            "query": query,
        },
    }


@router.post("/notes")
async def create_note(body: NoteBody):
    title = _clean_title(body.title)
    content = _clean_content(body.content)
    ts = now()
    note_id = new_id("note")
    storage = harness_instance().storage
    async with storage.connect() as db:
        async with db.execute("SELECT COALESCE(MIN(sort_order), 0) - 1 AS next FROM notes") as cursor:
            row = await cursor.fetchone()
        sort_order = int(row["next"] if row else -1)
        await db.execute(
            "INSERT INTO notes(id, title, content, sort_order, created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (note_id, title, content, sort_order, ts, ts),
        )
        await db.commit()
    return {"code": 200, "data": await _fetch_note(note_id)}


@router.put("/notes/reorder")
async def reorder_note(body: ReorderBody):
    note_id = str(body.note_id or "")
    storage = harness_instance().storage
    async with storage.connect() as db:
        async with db.execute(
            "SELECT id FROM notes ORDER BY sort_order ASC, created_at ASC, id ASC"
        ) as cursor:
            rows = await cursor.fetchall()
        ids = [row["id"] for row in rows]
        if note_id not in ids:
            return {"code": 404, "data": None, "message": "note not found"}
        ids.remove(note_id)
        target = max(0, min(int(body.target_index), len(ids)))
        ids.insert(target, note_id)
        for index, value in enumerate(ids):
            await db.execute("UPDATE notes SET sort_order=? WHERE id=?", (index, value))
        await db.commit()
    return {
        "code": 200,
        "data": {"id": note_id, "target_index": target, "total": len(ids)},
    }


@router.get("/notes/{note_id}")
async def get_note(note_id: str):
    note = await _fetch_note(note_id)
    if note is None:
        return {"code": 404, "data": None, "message": "note not found"}
    return {"code": 200, "data": note}


@router.put("/notes/{note_id}")
async def update_note(note_id: str, body: NoteBody):
    note = await _fetch_note(note_id)
    if note is None:
        return {"code": 404, "data": None, "message": "note not found"}
    storage = harness_instance().storage
    async with storage.connect() as db:
        await db.execute(
            "UPDATE notes SET title=?, content=?, updated_at=? WHERE id=?",
            (_clean_title(body.title), _clean_content(body.content), now(), note_id),
        )
        await db.commit()
    return {"code": 200, "data": await _fetch_note(note_id)}


@router.delete("/notes/{note_id}")
async def delete_note(note_id: str):
    storage = harness_instance().storage
    async with storage.connect() as db:
        async with db.execute("SELECT id FROM notes WHERE id=?", (note_id,)) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return {"code": 404, "data": None, "message": "note not found"}
        await db.execute("DELETE FROM notes WHERE id=?", (note_id,))
        await db.commit()
    return {"code": 200, "data": {"id": note_id, "deleted": True}}
