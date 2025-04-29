import os
import re
import uuid
import json
from datetime import datetime, timedelta

from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

import certifi
from motor.motor_asyncio import AsyncIOMotorClient

# ─── CONFIG ────────────────────────────────────────────────────────────────────
MONGO_URI = os.getenv("MONGO_URI", "")
if not MONGO_URI:
    raise RuntimeError("Set MONGO_URI env var!")

# Initialize Motor with TLS + certifi’s CA bundle for Atlas
mongo = AsyncIOMotorClient(
    MONGO_URI,
    tls=True,
    tlsCAFile=certifi.where(),
)
db  = mongo["pastes_db"]
col = db["pastes"]

app       = FastAPI()
templates = Jinja2Templates(directory="templates")


# ─── HELPERS ────────────────────────────────────────────────────────────────────
def compute_expiry(created: datetime, expires: str) -> str | None:
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
    return (created + delta).isoformat()


# ─── ROUTES ─────────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# ─── CREATE PASTE ──────────────────────────────────────────────────────────────
@app.post("/api/paste")
async def create_paste(
    content: str      = Form(...),
    title: str        = Form("Untitled Paste"),
    syntax: str       = Form("none"),
    expires: str      = Form("never"),
    visibility: str   = Form("public")
):
    now      = datetime.utcnow()
    paste_id = uuid.uuid4().hex[:8]
    record   = {
        "id":         paste_id,
        "content":    content,
        "title":      title,
        "syntax":     syntax,
        "visibility": visibility,
        "created_at": now.isoformat(),
        "expires_at": compute_expiry(now, expires)
    }
    await col.insert_one(record)
    return {"url": f"/paste/{paste_id}"}


# ─── VIEW PASTE ────────────────────────────────────────────────────────────────
@app.get("/paste/{paste_id}", response_class=HTMLResponse)
async def view_paste(request: Request, paste_id: str):
    rec = await col.find_one({"id": paste_id})
    if not rec:
        raise HTTPException(404, "Paste not found")
    exp = rec.get("expires_at")
    if exp and datetime.utcnow() >= datetime.fromisoformat(exp):
        raise HTTPException(404, "Paste expired")
    return templates.TemplateResponse("paste.html", {
        "request":  request,
        "paste_id": rec["id"],
        "title":    rec["title"],
        "content":  rec["content"]
    })


# ─── TOP PASTES ───────────────────────────────────────────────────────────────
@app.get("/api/top")
async def top_pastes():
    cursor = col.find({
        "$or": [
            {"expires_at": None},
            {"expires_at": {"$gt": datetime.utcnow().isoformat()}}
        ]
    }).sort([("content", -1)]).limit(10)
    docs = await cursor.to_list(10)
    return [{"id": d["id"], "title": d["title"]} for d in docs]


# ─── RECENT PASTES ─────────────────────────────────────────────────────────────
@app.get("/api/recent")
async def recent_pastes():
    cursor = col.find({
        "$or": [
            {"expires_at": None},
            {"expires_at": {"$gt": datetime.utcnow().isoformat()}}
        ]
    }).sort([("created_at", -1)]).limit(10)
    docs = await cursor.to_list(10)
    return [{"id": d["id"], "title": d["title"]} for d in docs]


# ─── HEALTHCHECK ───────────────────────────────────────────────────────────────
@app.get("/ping")
async def ping():
    return {"status": "alive"}


# ─── STARTUP ────────────────────────────────────────────────────────────────────
def start():
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))

if __name__ == "__main__":
    start()
