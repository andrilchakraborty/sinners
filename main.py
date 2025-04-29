import uuid
import os
import glob
import json
import aiofiles
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

# --- setup ---
app = FastAPI()
templates = Jinja2Templates(directory="templates")

PASTES_DIR = "pastes"
os.makedirs(PASTES_DIR, exist_ok=True)


# --- serve create/search page ---
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# --- create new paste ---
@app.post("/api/paste")
async def create_paste(
    content: str = Form(...),
    title: str = Form("Untitled Paste"),
    syntax: str = Form("none"),
    expires: str = Form("never"),
    visibility: str = Form("public")
):
    paste_id = uuid.uuid4().hex[:8]
    txt_path = os.path.join(PASTES_DIR, f"{paste_id}.txt")
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
    # sort by size descending
    top_files = sorted(files, key=lambda fp: os.path.getsize(fp), reverse=True)[:10]

    result = []
    for txt_fp in top_files:
        pid = os.path.splitext(os.path.basename(txt_fp))[0]
        meta_fp = os.path.join(PASTES_DIR, f"{pid}.json")

        title = pid
        if os.path.exists(meta_fp):
            async with aiofiles.open(meta_fp, "r") as f_meta:
                data = await f_meta.read()
                try:
                    title = json.loads(data).get("title", pid)
                except json.JSONDecodeError:
                    pass

        result.append({"id": pid, "title": title})

    return result


# --- view a paste by ID ---
@app.get("/paste/{paste_id}", response_class=HTMLResponse)
async def view_paste(request: Request, paste_id: str):
    filename = f"{paste_id}.txt"
    filepath = os.path.join(PASTES_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Paste not found")

    async with aiofiles.open(filepath, "r") as f:
        content = await f.read()

    return templates.TemplateResponse("paste.html", {
        "request": request,
        "paste_id": paste_id,
        "content": content
    })


# --- recent pastes (by modification time) ---
@app.get("/api/recent")
async def recent_pastes():
    files = glob.glob(os.path.join(PASTES_DIR, "*.txt"))
    # sort by mtime descending
    recent_files = sorted(files, key=lambda fp: os.path.getmtime(fp), reverse=True)[:10]

    result = []
    for txt_fp in recent_files:
        pid = os.path.splitext(os.path.basename(txt_fp))[0]
        meta_fp = os.path.join(PASTES_DIR, f"{pid}.json")

        title = pid
        if os.path.exists(meta_fp):
            async with aiofiles.open(meta_fp, "r") as f_meta:
                data = await f_meta.read()
                try:
                    title = json.loads(data).get("title", pid)
                except json.JSONDecodeError:
                    pass

        result.append({"id": pid, "title": title})

    return result


def start():
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))


if __name__ == "__main__":
    start()
