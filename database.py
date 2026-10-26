"""
database.py
-----------
SQLite persistence layer for the 3D Text Counter.

Design notes
------------
* The DB file lives next to this script, so the app works no matter which
  directory it is launched from (the old version used a relative path and
  would silently create a second, empty DB).
* init_db() is an idempotent migrator: it creates the table if missing, adds
  any new metric columns introduced by later versions, and back-fills them
  for rows written by an older build.
* All analysis is delegated to analytics.py - this module only stores and
  aggregates.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

import analytics

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "counter.db")

# column name -> SQLite declaration (used for both CREATE and migration)
METRIC_COLUMNS: Dict[str, str] = {
    "char_count": "INTEGER DEFAULT 0",
    "char_no_space": "INTEGER DEFAULT 0",
    "word_count": "INTEGER DEFAULT 0",
    "unique_word_count": "INTEGER DEFAULT 0",
    "sentence_count": "INTEGER DEFAULT 0",
    "line_count": "INTEGER DEFAULT 0",
    "paragraph_count": "INTEGER DEFAULT 0",
    "letters": "INTEGER DEFAULT 0",
    "digits": "INTEGER DEFAULT 0",
    "spaces": "INTEGER DEFAULT 0",
    "punctuation": "INTEGER DEFAULT 0",
    "uppercase": "INTEGER DEFAULT 0",
    "vowels": "INTEGER DEFAULT 0",
    "avg_word_len": "REAL DEFAULT 0",
    "avg_sentence_len": "REAL DEFAULT 0",
    "lexical_diversity": "REAL DEFAULT 0",
    "longest_word": "TEXT DEFAULT ''",
    "reading_seconds": "REAL DEFAULT 0",
    "flesch_score": "REAL DEFAULT 0",
    "readability": "TEXT DEFAULT ''",
}

TIME_COLUMNS: Dict[str, str] = {
    "date_str": "TEXT DEFAULT ''",
    "time_str": "TEXT DEFAULT ''",
    "hour": "INTEGER DEFAULT 0",
    "weekday": "INTEGER DEFAULT 0",
}


# --------------------------------------------------------------------------
# Connection / schema
# --------------------------------------------------------------------------

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create the schema, migrate new columns, back-fill legacy rows."""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS texts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )

    cur.execute("PRAGMA table_info(texts)")
    existing = {row["name"] for row in cur.fetchall()}

    for column, decl in {**METRIC_COLUMNS, **TIME_COLUMNS}.items():
        if column not in existing:
            cur.execute(f"ALTER TABLE texts ADD COLUMN {column} {decl}")

    conn.commit()

    # Back-fill anything written before the metric columns existed.
    cur.execute(
        """
        SELECT id, text, created_at FROM texts
        WHERE date_str IS NULL OR date_str = '' OR readability IS NULL OR readability = ''
        """
    )
    legacy = cur.fetchall()

    for row in legacy:
        metrics = analytics.analyze(row["text"] or "")
        try:
            dt = datetime.strptime(row["created_at"], "%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            dt = datetime.now()

        values = [metrics[col] for col in analytics.PERSISTED_METRICS]
        assignments = ", ".join(f"{col} = ?" for col in analytics.PERSISTED_METRICS)

        cur.execute(
            f"""
            UPDATE texts SET {assignments},
                date_str = ?, time_str = ?, hour = ?, weekday = ?
            WHERE id = ?
            """,
            (
                *values,
                dt.strftime("%Y-%m-%d"),
                dt.strftime("%H:%M:%S"),
                dt.hour,
                int(dt.strftime("%w")),
                row["id"],
            ),
        )

    for index_sql in (
        "CREATE INDEX IF NOT EXISTS idx_texts_created_at ON texts(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_texts_date_str ON texts(date_str)",
        "CREATE INDEX IF NOT EXISTS idx_texts_hour ON texts(hour)",
        "CREATE INDEX IF NOT EXISTS idx_texts_weekday ON texts(weekday)",
    ):
        cur.execute(index_sql)

    conn.commit()
    conn.close()


# --------------------------------------------------------------------------
# Writes
# --------------------------------------------------------------------------

def add_text_entry(text: str) -> Dict[str, Any]:
    """Analyze, store and return one entry (including non-persisted metrics)."""
    text = (text or "").strip()
    if not text:
        raise ValueError("Text cannot be empty")

    metrics = analytics.analyze(text)
    now = datetime.now()

    columns = ["text", "created_at", "date_str", "time_str", "hour", "weekday"]
    values: List[Any] = [
        text,
        now.strftime("%Y-%m-%d %H:%M:%S"),
        now.strftime("%Y-%m-%d"),
        now.strftime("%H:%M:%S"),
        now.hour,
        int(now.strftime("%w")),
    ]

    for col in analytics.PERSISTED_METRICS:
        columns.append(col)
        values.append(metrics[col])

    placeholders = ", ".join("?" for _ in columns)
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        f"INSERT INTO texts ({', '.join(columns)}) VALUES ({placeholders})",
        values,
    )
    new_id = cur.lastrowid
    conn.commit()
    conn.close()

    entry = dict(metrics)
    entry.update(
        {
            "id": new_id,
            "text": text,
            "created_at": values[1],
            "date_str": values[2],
            "time_str": values[3],
            "hour": values[4],
            "weekday": values[5],
        }
    )
    return entry


def delete_entry(entry_id: int) -> bool:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM texts WHERE id = ?", (entry_id,))
    deleted = cur.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def clear_all_entries() -> int:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM texts")
    total = cur.fetchone()[0]
    cur.execute("DELETE FROM texts")
    conn.commit()
    conn.close()
    return total


# --------------------------------------------------------------------------
# Reads / aggregates
# --------------------------------------------------------------------------

def get_summary_stats() -> Dict[str, Any]:
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT COUNT(*),
               COALESCE(SUM(word_count), 0),
               COALESCE(SUM(char_count), 0),
               COALESCE(SUM(sentence_count), 0),
               COALESCE(AVG(word_count), 0),
               COALESCE(AVG(avg_word_len), 0),
               COALESCE(AVG(flesch_score), 0),
               COALESCE(SUM(reading_seconds), 0),
               COALESCE(MAX(word_count), 0)
        FROM texts
        """
    )
    (
        overall,
        total_words,
        total_chars,
        total_sentences,
        avg_words_entry,
        avg_word_len,
        avg_flesch,
        total_reading,
        max_words,
    ) = cur.fetchone()

    today_str = date.today().strftime("%Y-%m-%d")
    cur.execute(
        "SELECT COUNT(*), COALESCE(SUM(word_count), 0), COALESCE(SUM(char_count), 0) "
        "FROM texts WHERE date_str = ?",
        (today_str,),
    )
    today_count, today_words, today_chars = cur.fetchone()

    yesterday_str = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
    cur.execute("SELECT COUNT(*) FROM texts WHERE date_str = ?", (yesterday_str,))
    yesterday_count = cur.fetchone()[0]

    now = datetime.now()
    cur.execute(
        "SELECT COUNT(*) FROM texts WHERE created_at >= ?",
        ((now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"),),
    )
    last_1h = cur.fetchone()[0]

    cur.execute(
        "SELECT COUNT(*) FROM texts WHERE created_at >= ?",
        ((now - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S"),),
    )
    last_30m = cur.fetchone()[0]

    week_start = (date.today() - timedelta(days=6)).strftime("%Y-%m-%d")
    cur.execute(
        "SELECT COUNT(*), COALESCE(SUM(word_count), 0) FROM texts WHERE date_str >= ?",
        (week_start,),
    )
    week_count, week_words = cur.fetchone()

    # Busiest hour and busiest day overall
    cur.execute(
        "SELECT hour, COUNT(*) c FROM texts GROUP BY hour ORDER BY c DESC, hour ASC LIMIT 1"
    )
    peak_hour_row = cur.fetchone()

    cur.execute(
        "SELECT date_str, COUNT(*) c FROM texts WHERE date_str != '' "
        "GROUP BY date_str ORDER BY c DESC, date_str DESC LIMIT 1"
    )
    peak_day_row = cur.fetchone()

    cur.execute("SELECT COUNT(DISTINCT date_str) FROM texts WHERE date_str != ''")
    active_days = cur.fetchone()[0]

    cur.execute("SELECT created_at FROM texts ORDER BY id DESC LIMIT 1")
    last_row = cur.fetchone()

    conn.close()

    change_vs_yesterday = 0.0
    if yesterday_count:
        change_vs_yesterday = round((today_count - yesterday_count) * 100 / yesterday_count, 1)
    elif today_count:
        change_vs_yesterday = 100.0

    return {
        "overall": overall,
        "today": today_count,
        "today_words": today_words,
        "today_chars": today_chars,
        "yesterday": yesterday_count,
        "change_vs_yesterday": change_vs_yesterday,
        "last_1h": last_1h,
        "last_30m": last_30m,
        "this_week": week_count,
        "this_week_words": week_words,
        "total_words": total_words,
        "total_chars": total_chars,
        "total_sentences": total_sentences,
        "avg_words_per_entry": round(float(avg_words_entry), 1),
        "avg_word_length": round(float(avg_word_len), 2),
        "avg_readability": round(float(avg_flesch), 1),
        "total_reading_seconds": round(float(total_reading), 1),
        "longest_entry_words": max_words,
        "active_days": active_days,
        "peak_hour": peak_hour_row["hour"] if peak_hour_row else None,
        "peak_hour_count": peak_hour_row["c"] if peak_hour_row else 0,
        "peak_day": peak_day_row["date_str"] if peak_day_row else None,
        "peak_day_count": peak_day_row["c"] if peak_day_row else 0,
        "last_entry_at": last_row["created_at"] if last_row else None,
        "db_file": os.path.basename(DB_NAME),
    }


def get_day_wise_stats(days: int = 7) -> List[Dict[str, Any]]:
    """Continuous day-by-day series (zero-filled) for the last `days` days."""
    conn = get_connection()
    cur = conn.cursor()

    start_date = date.today() - timedelta(days=days - 1)
    cur.execute(
        """
        SELECT date_str,
               COUNT(*) AS count,
               COALESCE(SUM(word_count), 0) AS words,
               COALESCE(SUM(char_count), 0) AS chars,
               COALESCE(AVG(avg_word_len), 0) AS avg_len
        FROM texts
        WHERE date_str >= ?
        GROUP BY date_str
        """,
        (start_date.strftime("%Y-%m-%d"),),
    )
    found = {row["date_str"]: dict(row) for row in cur.fetchall()}
    conn.close()

    series: List[Dict[str, Any]] = []
    for offset in range(days):
        current = start_date + timedelta(days=offset)
        key = current.strftime("%Y-%m-%d")
        row = found.get(key)
        series.append(
            {
                "date": key,
                "display": current.strftime("%b %d"),
                "day_name": current.strftime("%a"),
                "is_today": key == date.today().strftime("%Y-%m-%d"),
                "count": row["count"] if row else 0,
                "words": row["words"] if row else 0,
                "chars": row["chars"] if row else 0,
                "avg_word_len": round(float(row["avg_len"]), 2) if row else 0.0,
            }
        )
    return series


def get_hourly_stats(date_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    """24-slot breakdown for one date (defaults to today)."""
    date_filter = date_filter or date.today().strftime("%Y-%m-%d")

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT hour, COUNT(*) AS count,
               COALESCE(SUM(word_count), 0) AS words,
               COALESCE(SUM(char_count), 0) AS chars
        FROM texts WHERE date_str = ? GROUP BY hour
        """,
        (date_filter,),
    )
    found = {row["hour"]: dict(row) for row in cur.fetchall()}
    conn.close()

    return [
        {
            "hour": h,
            "label": f"{h:02d}:00",
            "count": found.get(h, {}).get("count", 0),
            "words": found.get(h, {}).get("words", 0),
            "chars": found.get(h, {}).get("chars", 0),
        }
        for h in range(24)
    ]


def get_weekday_stats() -> List[Dict[str, Any]]:
    """Lifetime distribution across the seven weekdays."""
    names = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
    short = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT weekday, COUNT(*) AS count, COALESCE(SUM(word_count), 0) AS words "
        "FROM texts GROUP BY weekday"
    )
    found = {int(row["weekday"]): dict(row) for row in cur.fetchall()}
    conn.close()

    return [
        {
            "weekday": i,
            "name": names[i],
            "short": short[i],
            "count": found.get(i, {}).get("count", 0),
            "words": found.get(i, {}).get("words", 0),
        }
        for i in range(7)
    ]


def get_keyword_stats(limit: int = 15, date_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    """Top keywords across every stored entry (optionally one day only)."""
    conn = get_connection()
    cur = conn.cursor()

    if date_filter:
        cur.execute("SELECT text FROM texts WHERE date_str = ?", (date_filter,))
    else:
        cur.execute("SELECT text FROM texts")

    corpus = "\n".join(row["text"] or "" for row in cur.fetchall())
    conn.close()

    return analytics.top_keywords(corpus, limit)


def get_recent_entries(
    limit: int = 50,
    search: Optional[str] = None,
    date_filter: Optional[str] = None,
    sort: str = "newest",
) -> List[Dict[str, Any]]:
    order = {
        "newest": "id DESC",
        "oldest": "id ASC",
        "longest": "char_count DESC",
        "words": "word_count DESC",
    }.get(sort, "id DESC")

    query = "SELECT * FROM texts WHERE 1=1"
    params: List[Any] = []

    if search:
        query += " AND text LIKE ?"
        params.append(f"%{search}%")
    if date_filter:
        query += " AND date_str = ?"
        params.append(date_filter)

    query += f" ORDER BY {order} LIMIT ?"
    params.append(limit)

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(query, params)
    rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    return rows


def get_entry(entry_id: int) -> Optional[Dict[str, Any]]:
    """One entry with the full (re-computed) metric set, including keywords."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM texts WHERE id = ?", (entry_id,))
    row = cur.fetchone()
    conn.close()

    if not row:
        return None

    entry = dict(row)
    entry.update(analytics.analyze(entry["text"] or ""))
    return entry


def get_all_entries() -> List[Dict[str, Any]]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM texts ORDER BY id ASC")
    rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    return rows
