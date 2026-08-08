import os
import uuid
import asyncio
import json
from pathlib import Path
from typing import Dict
from fastapi import FastAPI, Request, Depends, HTTPException, status, Form
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import secrets
import yt_dlp
import shutil

app = FastAPI()

# --- Настройки ---
USERS = {
    "freerambler": "GFX30610s$",
    "guest": "10241024",
}
DOWNLOAD_DIR = Path("/opt/yt-dlp-web/downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

# Сессии: token -> username
sessions: Dict[str, str] = {}
tasks: Dict[str, dict] = {}

def get_current_user(request: Request):
    token = request.cookies.get("session")
    if not token or token not in sessions:
        raise HTTPException(status_code=401, detail="Не авторизован")
    return sessions[token]

def user_dir(username: str) -> Path:
    d = DOWNLOAD_DIR / username
    d.mkdir(exist_ok=True)
    return d

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    token = request.cookies.get("session")
    if not token or token not in sessions:
        login_html = Path("/opt/yt-dlp-web/login.html").read_text()
        return HTMLResponse(login_html)
    html = Path("/opt/yt-dlp-web/index.html").read_text()
    return HTMLResponse(html)

@app.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    if USERS.get(username) != password:
        login_html = Path("/opt/yt-dlp-web/login.html").read_text()
        return HTMLResponse(login_html.replace("</form>", '<p style="color:#ff6a6a;text-align:center">Неверный логин или пароль</p></form>'), status_code=401)
    token = secrets.token_hex(32)
    sessions[token] = username
    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie("session", token, httponly=True, max_age=86400*7)
    return response

@app.get("/logout")
async def logout(request: Request):
    token = request.cookies.get("session")
    if token in sessions:
        del sessions[token]
    response = RedirectResponse(url="/", status_code=302)
    response.delete_cookie("session")
    return response

@app.post("/download")
async def start_download(request: Request, username: str = Depends(get_current_user)):
    data = await request.json()
    url = data.get("url", "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL не указан")
    task_id = str(uuid.uuid4())
    tasks[task_id] = {"status": "pending", "progress": 0, "filename": None, "error": None, "user": username, "title": ""}
    asyncio.create_task(do_download(task_id, url, username))
    return {"task_id": task_id}

async def do_download(task_id: str, url: str, username: str):
    out_dir = user_dir(username)
    tasks[task_id]["status"] = "downloading"

    def progress_hook(d):
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
            downloaded = d.get("downloaded_bytes", 0)
            if total:
                tasks[task_id]["progress"] = round(downloaded / total * 100, 1)
            tasks[task_id]["speed"] = d.get("_speed_str", "")
            tasks[task_id]["eta"] = d.get("_eta_str", "")
        elif d["status"] == "finished":
            tasks[task_id]["progress"] = 100
            tasks[task_id]["filename"] = Path(d["filename"]).name

    ydl_opts = {
        "format": "bestvideo[height<=1080][vcodec^=avc]+bestaudio[ext=m4a]/bestvideo[height<=1080][ext=mp4]+bestaudio/best[height<=1080]/best",
        "merge_output_format": "mp4",
        "outtmpl": str(out_dir / "%(title)s.%(ext)s"),
        "progress_hooks": [progress_hook],
        "quiet": True,
        "no_warnings": True,
        "extractor_args": {"youtube": {"js_runtimes": ["node"]}},
        "remote_components": ["ejs:github"],
    }

    try:
        loop = asyncio.get_event_loop()
        def run_ydl():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                tasks[task_id]["title"] = info.get("title", "")
        await loop.run_in_executor(None, run_ydl)
        tasks[task_id]["status"] = "done"
    except Exception as e:
        tasks[task_id]["status"] = "error"
        tasks[task_id]["error"] = str(e)

@app.get("/status/{task_id}")
async def get_status(task_id: str, username: str = Depends(get_current_user)):
    task = tasks.get(task_id)
    if not task or task["user"] != username:
        raise HTTPException(status_code=404)
    return task

@app.get("/tasks")
async def get_tasks(username: str = Depends(get_current_user)):
    return {k: v for k, v in tasks.items() if v["user"] == username}

@app.get("/files")
async def list_files(username: str = Depends(get_current_user)):
    d = user_dir(username)
    files = []
    for f in sorted(d.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if f.is_file():
            files.append({"name": f.name, "size": f.stat().st_size, "mtime": f.stat().st_mtime})
    return files

@app.get("/download-file/{filename}")
async def download_file(filename: str, username: str = Depends(get_current_user)):
    filepath = user_dir(username) / filename
    if not filepath.exists():
        raise HTTPException(status_code=404)
    return FileResponse(filepath, filename=filename, media_type="application/octet-stream")

@app.delete("/files/{filename}")
async def delete_file(filename: str, username: str = Depends(get_current_user)):
    filepath = user_dir(username) / filename
    if filepath.exists():
        filepath.unlink()
    return {"ok": True}

@app.get("/disk-stats")
async def disk_stats(username: str = Depends(get_current_user)):
    total, used, free = shutil.disk_usage("/")
    
    downloads_dir = Path("/opt/yt-dlp-web/downloads/freerambler")
    
    def dir_size(p: Path) -> int:
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.exists() else 0
    
    return {
        "total": total,
        "used": used,
        "free": free,
        "downloads": dir_size(downloads_dir),
    }
@app.post("/collect-links")
async def collect_links(username: str = Depends(get_current_user)):
    proc = await asyncio.create_subprocess_exec(
        "/opt/yt-dlp-web/venv/bin/python", "/opt/yt-dlp-web/yt_collector.py",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    return {"output": (stdout + stderr).decode()}

@app.get("/collected-links")
async def collected_links(username: str = Depends(get_current_user)):
    path = Path("/opt/yt-dlp-web/collected_links.json")
    if not path.exists():
        return []
    return json.loads(path.read_text())

@app.delete("/collected-links/{video_id}")
async def remove_collected_link(video_id: str, username: str = Depends(get_current_user)):
    path = Path("/opt/yt-dlp-web/collected_links.json")
    if path.exists():
        links = json.loads(path.read_text())
        links = [l for l in links if video_id not in l["url"]]
        path.write_text(json.dumps(links, ensure_ascii=False, indent=2))
    return {"ok": True}

@app.delete("/collected-links")
async def clear_collected_links(username: str = Depends(get_current_user)):
    path = Path("/opt/yt-dlp-web/collected_links.json")
    if path.exists():
        path.write_text("[]")
    return {"ok": True}
