import uuid
import json
import os
import glob
import asyncio
import aiofiles
import httpx
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

# --- setup ---
app = FastAPI()
templates = Jinja2Templates(directory="templates")

PASTES_DIR = "pastes"
os.makedirs(PASTES_DIR, exist_ok=True)

# Your Render service URL
SERVICE_URL = "https://sinners-pastes.onrender.com"


# --- serve create/search page ---
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# --- create new paste ---
@app.post("/api/paste")
async def create_paste(
    content: str      = Form(...),
    title: str        = Form("Untitled Paste"),
    syntax: str       = Form("none"),
    expires: str      = Form("never"),
    visibility: str   = Form("public")
):
    paste_id = uuid.uuid4().hex[:8]
    txt_path  = os.path.join(PASTES_DIR, f"{paste_id}.txt")
    meta_path = os.path.join(PASTES_DIR, f"{paste_id}.json")

    # save the raw content
    async with aiofiles.open(txt_path, "w") as f_txt:
        await f_txt.write(content)

    # save metadata (only title for now)
    meta = {"title": title}
    async with aiofiles.open(meta_path, "w") as f_meta:
        await f_meta.write(json.dumps(meta))

    return {"url": f"/paste/{paste_id}"}


# --- top pastes (by file size) ---
@app.get("/api/top")
async def top_pastes():
    files = glob.glob(os.path.join(PASTES_DIR, "*.txt"))
    top_files = sorted(files, key=lambda fp: os.path.getsize(fp), reverse=True)[:10]

    result = []
    for txt_fp in top_files:
        pid     = os.path.splitext(os.path.basename(txt_fp))[0]
        meta_fp = os.path.join(PASTES_DIR, f"{pid}.json")

        title = pid
        if os.path.exists(meta_fp):
            async with aiofiles.open(meta_fp, "r") as f_meta:
                raw = await f_meta.read()
                try:
                    title = json.loads(raw).get("title", pid) or pid
                except json.JSONDecodeError:
                    pass

        result.append({"id": pid, "title": title})

    return result


# --- view a paste by ID ---
@app.get("/paste/{paste_id}", response_class=HTMLResponse)
async def view_paste(request: Request, paste_id: str):
    txt_path = os.path.join(PASTES_DIR, f"{paste_id}.txt")
    if not os.path.exists(txt_path):
        raise HTTPException(status_code=404, detail="Paste not found")

    async with aiofiles.open(txt_path, "r") as f:
        content = await f.read()

    meta_path = os.path.join(PASTES_DIR, f"{paste_id}.json")
    title = paste_id
    if os.path.exists(meta_path):
        async with aiofiles.open(meta_path, "r") as f_meta:
            raw = await f_meta.read()
            try:
                data = json.loads(raw)
                title = data.get("title", paste_id) or paste_id
            except json.JSONDecodeError:
                pass

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

        title = pid
        if os.path.exists(meta_fp):
            async with aiofiles.open(meta_fp, "r") as f_meta:
                raw = await f_meta.read()
                try:
                    title = json.loads(raw).get("title", pid) or pid
                except json.JSONDecodeError:
                    pass

        result.append({"id": pid, "title": title})

    return result


# ─── Scheduled external ping ─────────────────────────────────────────────────
@app.on_event("startup")
async def schedule_ping_task():
    async def ping_loop():
        async with httpx.AsyncClient(timeout=5) as client:
            while True:
                try:
                    resp = await client.get(f"{SERVICE_URL}/ping")
                    # optionally log if non-200:
                    if resp.status_code != 200:
                        print(f"Health ping returned {resp.status_code}")
                except Exception as e:
                    print(f"External ping failed: {e!r}")
                await asyncio.sleep(10)  # wait 10 seconds

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
