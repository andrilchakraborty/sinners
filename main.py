from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
import uuid
import json
import os
import glob
import asyncio
import aiofiles
import httpx
from datetime import datetime
import logging

# --- setup ---
app = FastAPI()
templates = Jinja2Templates(directory="templates")
logger = logging.getLogger(__name__)
PASTES_DIR = "pastes"
os.makedirs(PASTES_DIR, exist_ok=True)

# Your Render service URL
SERVICE_URL = "https://sinners-pastes.onrender.com"

# --- serve create/search page ---
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# --- create a new paste ---
@app.post("/api/paste")
async def create_paste(
    content: str    = Form(...),
    title: str      = Form("Untitled Paste"),
    syntax: str     = Form("none"),
    visibility: str = Form("public")
):
    try:
        # enforce never-expire
        expires = "never"
        paste_id  = uuid.uuid4().hex[:8]
        txt_path  = os.path.join(PASTES_DIR, f"{paste_id}.txt")
        meta_path = os.path.join(PASTES_DIR, f"{paste_id}.json")

        # save the content
        async with aiofiles.open(txt_path, "w") as f_txt:
            await f_txt.write(content)

        # build metadata, initialize views = 0, never expire
        meta = {
            "title":      title,
            "syntax":     syntax,
            "visibility": visibility,
            "expires":    expires,
            "created_at": datetime.utcnow().isoformat(),
            "views":      0
        }
        async with aiofiles.open(meta_path, "w") as f_meta:
            await f_meta.write(json.dumps(meta, indent=2))

        return JSONResponse(status_code=200, content={"url": f"/paste/{paste_id}"})
    except Exception as e:
        logger.exception("Failed to create paste")
        return JSONResponse(
            status_code=500,
            content={"error": "Internal Server Error", "details": str(e)}
        )

# --- top pastes (by file size) ---
@app.get("/api/top")
async def top_pastes():
    files = glob.glob(os.path.join(PASTES_DIR, "*.txt"))
    top_files = sorted(files, key=lambda fp: os.path.getsize(fp), reverse=True)[:10]

    result = []
    for txt_fp in top_files:
        pid     = os.path.splitext(os.path.basename(txt_fp))[0]
        meta_fp = os.path.join(PASTES_DIR, f"{pid}.json")

        info = {"id": pid, "title": pid, "views": 0}
        if os.path.exists(meta_fp):
            async with aiofiles.open(meta_fp, "r") as f_meta:
                raw = await f_meta.read()
                try:
                    obj = json.loads(raw)
                    info["title"] = obj.get("title", pid) or pid
                    info["views"] = obj.get("views", 0)
                except json.JSONDecodeError:
                    pass

        result.append(info)
    return result

# --- view a paste by ID ---
@app.get("/paste/{paste_id}", response_class=HTMLResponse)
async def view_paste(request: Request, paste_id: str):
    txt_path = os.path.join(PASTES_DIR, f"{paste_id}.txt")
    meta_path = os.path.join(PASTES_DIR, f"{paste_id}.json")

    if not os.path.exists(txt_path):
        raise HTTPException(status_code=404, detail="Paste not found")

    # read content
    async with aiofiles.open(txt_path, "r") as f:
        content = await f.read()

    # load & increment views
    title = paste_id
    if os.path.exists(meta_path):
        async with aiofiles.open(meta_path, "r+") as f_meta:
            raw = await f_meta.read()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = {}
            data["views"] = data.get("views", 0) + 1
            title = data.get("title", paste_id) or paste_id
            await f_meta.seek(0)
            await f_meta.write(json.dumps(data, indent=2))
            await f_meta.truncate()
    return templates.TemplateResponse("paste.html", {
        "request":   request,
        "paste_id":  paste_id,
        "title":     title,
        "content":   content
    })

# --- recent pastes (by modification time) ---
@app.get("/api/recent")
async def recent_pastes():
    files = glob.glob(os.path.join(PASTES_DIR, "*.txt"))
    recent_files = sorted(files, key=lambda fp: os.path.getmtime(fp), reverse=True)[:10]

    result = []
    for txt_fp in recent_files:
        pid     = os.path.splitext(os.path.basename(txt_fp))[0]
        meta_fp = os.path.join(PASTES_DIR, f"{pid}.json")

        info = {"id": pid, "title": pid, "views": 0}
        if os.path.exists(meta_fp):
            async with aiofiles.open(meta_fp, "r") as f_meta:
                raw = await f_meta.read()
                try:
                    obj = json.loads(raw)
                    info["title"] = obj.get("title", pid) or pid
                    info["views"] = obj.get("views", 0)
                except json.JSONDecodeError:
                    pass

        result.append(info)
    return result

# --- all pastes (metadata list) ---
@app.get("/api/all")
async def list_all_pastes():
    result = []
    for meta_fp in glob.glob(os.path.join(PASTES_DIR, "*.json")):
        pid = os.path.splitext(os.path.basename(meta_fp))[0]
        async with aiofiles.open(meta_fp, "r") as f_meta:
            raw = await f_meta.read()
        try:
            meta = json.loads(raw)
        except json.JSONDecodeError:
            meta = {}
        entry = {
            "id":         pid,
            "title":      meta.get("title", pid),
            "syntax":     meta.get("syntax", "none"),
            "visibility": meta.get("visibility", "public"),
            "expires":    "never",
            "created_at": meta.get("created_at", ""),
            "views":      meta.get("views", 0)
        }
        result.append(entry)
    return JSONResponse(content=result)

# ─── Scheduled external ping ─────────────────────────────────────────────────
@app.on_event("startup")
async def schedule_ping_task():
    async def ping_loop():
        async with httpx.AsyncClient(timeout=5) as client:
            while True:
                try:
                    resp = await client.get(f"{SERVICE_URL}/ping")
                    if resp.status_code != 200:
                        print(f"Health ping returned {resp.status_code}")
                except Exception as e:
                    print(f"External ping failed: {e!r}")
                await asyncio.sleep(10)
    asyncio.create_task(ping_loop())

# ─── HEALTHCHECK ───────────────────────────────────────────────────────────────
@app.get("/ping")
async def ping():
    return {"status": "alive"}


def start():
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))

if __name__ == "__main__":
    start()
