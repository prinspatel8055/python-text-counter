"""
app.py
------
FastAPI application for the 3D Text Counter & Analytics dashboard.

Run:
    python app.py          # picks a free port, opens the browser
    uvicorn app:app --reload

Layers:
    analytics.py  ->  pure text metrics
    database.py   ->  SQLite storage + aggregation
    app.py        ->  HTTP API + static page (this file)
"""

from __future__ import annotations

import csv
import io
import json
import os
import socket
import threading
import webbrowser
from datetime import date
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import analytics
import database

APP_VERSION = "2.0.0"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")
INDEX_FILE = os.path.join(TEMPLATES_DIR, "index.html")

database.init_db()

app = FastAPI(
    title="3D Text Counter & Analytics API",
    version=APP_VERSION,
    description=(
        "Stores text entries in SQLite and returns deep text analytics: "
        "counts, composition, readability and time-based trends."
    ),
)

if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------

class TextInput(BaseModel):
    text: str = Field(..., description="Raw text to analyze and store")


# --------------------------------------------------------------------------
# Page
# --------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
def read_root():
    if not os.path.exists(INDEX_FILE):
        raise HTTPException(status_code=404, detail="templates/index.html not found")
    return FileResponse(INDEX_FILE, media_type="text/html")


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "version": APP_VERSION,
        "database": os.path.basename(database.DB_NAME),
        "server_date": date.today().strftime("%Y-%m-%d"),
    }


# --------------------------------------------------------------------------
# Analysis + entries
# --------------------------------------------------------------------------

@app.post("/api/analyze")
def analyze_only(payload: TextInput):
    """Full metric set for a piece of text WITHOUT saving it."""
    return analytics.analyze(payload.text or "")


@app.post("/api/texts")
def create_text(payload: TextInput):
    try:
        return database.add_text_entry(payload.text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # pragma: no cover - surfaced to the UI
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/texts")
def list_texts(
    limit: int = Query(50, ge=1, le=500),
    search: Optional[str] = Query(None),
    date: Optional[str] = Query(None, alias="date"),
    sort: str = Query("newest", pattern="^(newest|oldest|longest|words)$"),
):
    return database.get_recent_entries(limit=limit, search=search, date_filter=date, sort=sort)


@app.get("/api/texts/{entry_id}")
def read_text(entry_id: int):
    entry = database.get_entry(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    return entry


@app.delete("/api/texts/{entry_id}")
def delete_text(entry_id: int):
    if not database.delete_entry(entry_id):
        raise HTTPException(status_code=404, detail="Entry not found")
    return {"status": "deleted", "id": entry_id}


@app.delete("/api/texts")
def clear_texts(confirm: bool = Query(False, description="Must be true to wipe the table")):
    if not confirm:
        raise HTTPException(status_code=400, detail="Pass ?confirm=true to clear all entries")
    removed = database.clear_all_entries()
    return {"status": "cleared", "removed": removed}


# --------------------------------------------------------------------------
# Statistics
# --------------------------------------------------------------------------

@app.get("/api/stats")
def stats():
    return database.get_summary_stats()


@app.get("/api/stats/daywise")
def stats_daywise(days: int = Query(7, ge=1, le=90)):
    return database.get_day_wise_stats(days)


@app.get("/api/stats/hourly")
def stats_hourly(date: Optional[str] = Query(None)):
    return database.get_hourly_stats(date)


@app.get("/api/stats/weekday")
def stats_weekday():
    return database.get_weekday_stats()


@app.get("/api/stats/keywords")
def stats_keywords(
    limit: int = Query(15, ge=1, le=60),
    date: Optional[str] = Query(None),
):
    return database.get_keyword_stats(limit=limit, date_filter=date)


@app.get("/api/stats/overview")
def stats_overview(days: int = Query(7, ge=1, le=90)):
    """Everything the dashboard needs in a single round-trip."""
    return {
        "summary": database.get_summary_stats(),
        "daywise": database.get_day_wise_stats(days),
        "hourly": database.get_hourly_stats(None),
        "weekday": database.get_weekday_stats(),
        "keywords": database.get_keyword_stats(15),
    }


# --------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------

@app.get("/api/export")
def export(format: str = Query("csv", pattern="^(csv|json)$")):
    rows = database.get_all_entries()

    if format == "json":
        payload = json.dumps(rows, indent=2, ensure_ascii=False)
        return StreamingResponse(
            io.StringIO(payload),
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="text_counter_export.json"'},
        )

    buffer = io.StringIO()
    fieldnames = list(rows[0].keys()) if rows else ["id", "text", "created_at"]
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="text_counter_export.csv"'},
    )


@app.exception_handler(ValueError)
def value_error_handler(_request, exc: ValueError):  # pragma: no cover
    return JSONResponse(status_code=400, content={"detail": str(exc)})


# --------------------------------------------------------------------------
# Launcher
# --------------------------------------------------------------------------

def find_free_port(default_port: int = 8000) -> int:
    """Use 8000 when free, otherwise let the OS hand us an open port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        if probe.connect_ex(("127.0.0.1", default_port)) != 0:
            return default_port

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as fallback:
        fallback.bind(("127.0.0.1", 0))
        return fallback.getsockname()[1]


def open_browser_later(url: str, delay: float = 1.2) -> None:
    threading.Timer(delay, lambda: webbrowser.open(url)).start()


if __name__ == "__main__":
    port = find_free_port(8000)
    url = f"http://127.0.0.1:{port}"

    line = "=" * 64
    print(line)
    print("        3D TEXT COUNTER  &  DEEP TEXT ANALYTICS".center(64))
    print(line)
    print(f"  Version        : {APP_VERSION}")
    print(f"  Database       : {os.path.basename(database.DB_NAME)} (SQLite, connected)")
    print(f"  Dashboard      : {url}")
    print(f"  API docs       : {url}/docs")
    print("  Opening your browser automatically...")
    print("  Press Ctrl+C in this window to stop the server.")
    print(line)

    open_browser_later(url)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
