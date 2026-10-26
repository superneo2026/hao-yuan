from __future__ import annotations

import csv
import io
from collections import defaultdict

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from configs.configs import prefix
from core.harness import get_harness
from core.storage import now
from extensions.common import ok

router = APIRouter(prefix=prefix, tags=["usage"])


@router.get("/usage/today")
async def usage_today():
    harness = await get_harness()
    return ok(await harness.storage.usage_today())


@router.get("/usage/daily")
async def usage_daily(days: int = 14):
    harness = await get_harness()
    rows = await harness.storage._fetch(
        "SELECT day, SUM(prompt_tokens) AS prompt_tokens, SUM(completion_tokens) AS completion_tokens,"
        " SUM(cost_est) AS cost_est FROM usage_daily GROUP BY day ORDER BY day DESC LIMIT ?",
        (max(1, min(days, 120)),),
    )
    return ok(list(reversed(rows)))


@router.get("/usage/by-model")
async def usage_by_model():
    harness = await get_harness()
    rows = await harness.storage._fetch(
        "SELECT provider, model, SUM(prompt_tokens) AS prompt_tokens, SUM(completion_tokens) AS completion_tokens,"
        " SUM(cost_est) AS cost_est FROM usage_daily GROUP BY provider, model ORDER BY prompt_tokens DESC"
    )
    return ok(rows)


@router.get("/usage/export.csv")
async def export_csv():
    harness = await get_harness()
    rows = await harness.storage._fetch("SELECT * FROM usage_daily ORDER BY day DESC, provider, model")
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["day", "provider", "model", "prompt_tokens", "completion_tokens", "cached_tokens", "reasoning_tokens", "cost_est"])
    for row in rows:
        writer.writerow(
            [
                row.get("day"),
                row.get("provider"),
                row.get("model"),
                row.get("prompt_tokens", 0),
                row.get("completion_tokens", 0),
                row.get("cached_tokens", 0),
                row.get("reasoning_tokens", 0),
                row.get("cost_est", 0),
            ]
        )
    data = buffer.getvalue().encode("utf-8-sig")
    return StreamingResponse(
        iter([data]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="haoyuan-usage-{now()[:10]}.csv"'},
    )
