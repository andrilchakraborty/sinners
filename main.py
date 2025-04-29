
import os
import re
import uuid
import json
import aiosqlite
from datetime import datetime, timedelta

from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates


DB_PATH    = os.getenv("PASTE_DB", "pastes.db")
PASTES_DIR = "pastes"           
os.makedirs(PASTES_DIR, exist_ok=True)

app       = FastAPI()
templates = Jinja2Templates(directory="templates")



@app.on_event("startup")
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS pastes (
                id          TEXT PRIMARY KEY,
                content     TEXT        NOT NULL,
                title       TEXT        NOT NULL,
                syntax      TEXT        NOT NULL,
                visibility  TEXT        NOT NULL,
                created_at  TIMESTAMP   NOT NULL,
                expires_at  TIMESTAMP   NULL
            )
        """)
        await db.commit()


# --- helper to compute expiration timestamps ---
def compute_expiry(created: datetime, expires: str) -> datetime | None:
    """
    expires: 'never' or e.g. '10m', '2h', '3d'
    """
    if expires == "never":
        return None

    m = re.match(r"^(\d+)([smhd])$", expires)
    if not m:
        return None

    n, unit = int(m.group(1)), m.group(2)
    delta = {
        "s": timedelta(seconds=n),
        "m": timedelta(minutes=n),
        "h": timedelta(hours=n),
        "d": timedelta(days=n),
    }[unit]
    return created + delta


async def is_still_valid(db: aiosqlite.Connection, paste_id: str) -> bool:
    # fetch expires_at
    cursor = await db.execute(
        "SELECT expires_at FROM pastes WHERE id = ?",
        (paste_id,)
    )
    row = await cursor.fetchone()
    await cursor.close()

    if not row:
        return False

    (expires_at,) = row
    if expires_at is None:
        return True

    return datetime.utcnow() < datetime.fromisoformat(expires_at)


# --- home page / paste form ---
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# --- create new paste ---
@app.post("/api/paste")
async def create_paste(
    content: str      = Form(...),
    title: str        = Form("Untitled Paste"),
    syntax: str       = Form("none"),
    expires: str      = Form("never"),   # 'never' or '10m', '2h', etc.
    visibility: str   = Form("public")   # not yet enforced
):
    paste_id   = uuid.uuid4().hex[:8]
    now        = datetime.utcnow()
    expires_at = compute_expiry(now, expires)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO pastes (
                id, content, title, syntax, visibility, created_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                paste_id,
                content,
                title,
                syntax,
                visibility,
                now.isoformat(),
                expires_at.isoformat() if expires_at else None
            )
        )
        await db.commit()

    return {"url": f"/paste/{paste_id}"}


# --- view one paste ---
@app.get("/paste/{paste_id}", response_class=HTMLResponse)
async def view_paste(request: Request, paste_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        if not await is_still_valid(db, paste_id):
            raise HTTPException(status_code=404, detail="Paste not found or expired")

        cursor = await db.execute(
            "SELECT content, title FROM pastes WHERE id = ?",
            (paste_id,)
        )
        row = await cursor.fetchone()
        await cursor.close()

    if not row:
        # shouldn't happen if is_still_valid passed, but just in case
        raise HTTPException(status_code=404, detail="Paste not found")
    content, title = row

    return templates.TemplateResponse("paste.html", {
        "request":  request,
        "paste_id": paste_id,
        "title":    title,
        "content":  content
    })


# --- list top pastes (largest) ---
@app.get("/api/top")
async def top_pastes():
    now_iso = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            SELECT id, title, LENGTH(content) AS size
              FROM pastes
             WHERE expires_at IS NULL OR expires_at > ?
             ORDER BY size DESC
             LIMIT 10
            """,
            (now_iso,)
        )
        rows = await cursor.fetchall()
        await cursor.close()

    return [{"id": pid, "title": title} for pid, title, _ in rows]


# --- list recent pastes (newest) ---
@app.get("/api/recent")
async def recent_pastes():
    now_iso = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            SELECT id, title
              FROM pastes
             WHERE expires_at IS NULL OR expires_at > ?
             ORDER BY created_at DESC
             LIMIT 10
            """,
            (now_iso,)
        )
        rows = await cursor.fetchall()
        await cursor.close()

    return [{"id": pid, "title": title} for pid, title in rows]


# --- new keep-alive endpoint for uptime monitors ---
@app.get("/ping")
async def ping():
    return {"status": "alive"}


# --- run with uvicorn ---
def start():
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))


if __name__ == "__main__":
    start()
