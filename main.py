import os
import re
import uuid
import json
import boto3
from datetime import datetime, timedelta

from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

# ─── CONFIG ────────────────────────────────────────────────────────────────────
AWS_REGION      = os.getenv("AWS_REGION", "us-east-1")
S3_BUCKET       = os.getenv("PASTES_S3_BUCKET", "")
if not S3_BUCKET:
    raise RuntimeError("Set PASTES_S3_BUCKET env var!")

s3 = boto3.client("s3", region_name=AWS_REGION)
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
    delta = {"s": timedelta(seconds=n),
             "m": timedelta(minutes=n),
             "h": timedelta(hours=n),
             "d": timedelta(days=n)}[unit]
    return (created + delta).isoformat()

def s3_key(paste_id: str) -> str:
    return f"pastes/{paste_id}.json"

def save_paste(record: dict) -> None:
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=s3_key(record["id"]),
        Body=json.dumps(record),
        ContentType="application/json"
    )

def load_paste(paste_id: str) -> dict | None:
    try:
        obj = s3.get_object(Bucket=S3_BUCKET, Key=s3_key(paste_id))
    except s3.exceptions.NoSuchKey:
        return None
    body = obj["Body"].read()
    return json.loads(body)

def list_all_pastes() -> list[dict]:
    objs = s3.list_objects_v2(Bucket=S3_BUCKET, Prefix="pastes/").get("Contents", [])
    now = datetime.utcnow()
    recs = []
    for o in objs:
        if not o["Key"].endswith(".json"):
            continue
        pid = os.path.basename(o["Key"])[:-5]
        rec = load_paste(pid)
        if not rec:
            continue
        exp = rec.get("expires_at")
        if exp is None or now < datetime.fromisoformat(exp):
            recs.append(rec)
    return recs


# ─── ROUTES ─────────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/api/paste")
async def create_paste(
    content: str    = Form(...),
    title: str      = Form("Untitled Paste"),
    syntax: str     = Form("none"),
    expires: str    = Form("never"),
    visibility: str = Form("public")
):
    now = datetime.utcnow()
    paste_id = uuid.uuid4().hex[:8]
    record = {
        "id":         paste_id,
        "content":    content,
        "title":      title,
        "syntax":     syntax,
        "visibility": visibility,
        "created_at": now.isoformat(),
        "expires_at": compute_expiry(now, expires)
    }
    save_paste(record)
    return {"url": f"/paste/{paste_id}"}

@app.get("/paste/{paste_id}", response_class=HTMLResponse)
async def view_paste(request: Request, paste_id: str):
    rec = load_paste(paste_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Paste not found")
    exp = rec.get("expires_at")
    if exp is not None and datetime.utcnow() >= datetime.fromisoformat(exp):
        raise HTTPException(status_code=404, detail="Paste expired")
    return templates.TemplateResponse("paste.html", {
        "request":  request,
        "paste_id": rec["id"],
        "title":    rec["title"],
        "content":  rec["content"]
    })

@app.get("/api/top")
async def top_pastes():
    recs = list_all_pastes()
    recs.sort(key=lambda r: len(r["content"]), reverse=True)
    return [{"id": r["id"], "title": r["title"]} for r in recs[:10]]

@app.get("/api/recent")
async def recent_pastes():
    recs = list_all_pastes()
    recs.sort(key=lambda r: r["created_at"], reverse=True)
    return [{"id": r["id"], "title": r["title"]} for r in recs[:10]]

@app.get("/ping")
async def ping():
    return {"status": "alive"}

# ─── STARTUP ────────────────────────────────────────────────────────────────────
def start():
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT","8000")))

if __name__ == "__main__":
    start()
