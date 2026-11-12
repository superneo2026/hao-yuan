from __future__ import annotations


def _clear_notes(client):
    data = client.get("/api/notes", params={"page_size": 50}).json()["data"]
    for item in data["items"]:
        client.delete(f"/api/notes/{item['id']}")


def _create(client, title, content=""):
    body = client.post("/api/notes", json={"title": title, "content": content}).json()
    assert body["code"] == 200, body
    return body["data"]


def _ids(client, **params):
    body = client.get("/api/notes", params=params).json()
    assert body["code"] == 200, body
    return [item["id"] for item in body["data"]["items"]]


def test_notes_crud(client):
    _clear_notes(client)

    note = _create(client, "Roadmap", "Ship the notes drawer")
    assert note["title"] == "Roadmap"
    assert note["content"] == "Ship the notes drawer"

    fetched = client.get(f"/api/notes/{note['id']}").json()
    assert fetched["code"] == 200
    assert fetched["data"]["id"] == note["id"]

    search = client.get("/api/notes", params={"q": "notes drawer"}).json()["data"]
    assert search["total"] == 1
    assert search["items"][0]["id"] == note["id"]

    updated = client.put(
        f"/api/notes/{note['id']}", json={"title": "Roadmap v2", "content": "Updated"}
    ).json()
    assert updated["code"] == 200
    assert updated["data"]["title"] == "Roadmap v2"
    assert updated["data"]["content"] == "Updated"

    blank = client.put(f"/api/notes/{note['id']}", json={"title": "  ", "content": ""}).json()
    assert blank["data"]["title"] == "无标题笔记"

    removed = client.delete(f"/api/notes/{note['id']}").json()
    assert removed["code"] == 200
    assert client.get(f"/api/notes/{note['id']}").json()["code"] == 404

    _clear_notes(client)


def test_notes_pagination_and_cross_page_reorder(client):
    _clear_notes(client)
    created = [_create(client, f"Note {i}") for i in range(1, 6)]

    # Newest notes are inserted at the top.
    assert _ids(client, page=1, page_size=10) == [item["id"] for item in reversed(created)]

    first_page = client.get("/api/notes", params={"page": 1, "page_size": 2}).json()["data"]
    assert first_page["total"] == 5
    assert first_page["pages"] == 3
    assert len(first_page["items"]) == 2

    last = created[0]["id"]
    moved = client.put("/api/notes/reorder", json={"note_id": last, "target_index": 0}).json()
    assert moved["code"] == 200
    order = [item["id"] for item in reversed(created)]
    order.remove(last)
    order.insert(0, last)
    assert _ids(client, page=1, page_size=10) == order

    # Move the final note to the second slot, crossing a page boundary.
    final = order[-1]
    assert client.put("/api/notes/reorder", json={"note_id": final, "target_index": 1}).json()["code"] == 200
    order.remove(final)
    order.insert(1, final)
    assert _ids(client, page=1, page_size=10) == order
    assert _ids(client, page=2, page_size=2) == order[2:4]

    clamped = client.put("/api/notes/reorder", json={"note_id": order[0], "target_index": 999}).json()
    assert clamped["code"] == 200
    assert clamped["data"]["target_index"] == 4

    _clear_notes(client)
