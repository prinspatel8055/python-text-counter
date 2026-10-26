# 3D Text Counter &amp; Deep Text Analytics

A local-first text analytics dashboard. Type or paste text, and the app
extrudes it as real 3D metallic type, measures it on 20+ linguistic
dimensions, stores it in SQLite, and charts your writing activity by day,
weekday and hour.

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  index.html  │───▶│    app.py    │───▶│ database.py  │
│  UI + 3D     │◀───│  FastAPI     │◀───│  SQLite      │
└──────────────┘    └──────┬───────┘    └──────────────┘
                           │
                    ┌──────▼───────┐
                    │ analytics.py │  pure text metrics
                    └──────────────┘
```

---

## 1. Running it

### Windows
Double-click **`run.bat`**. It checks for Python, installs the dependencies
the first time, starts the server and opens your browser.

### macOS / Linux
```bash
chmod +x run.sh
./run.sh
```

### Manual
```bash
pip install -r requirements.txt
python app.py
```

The server picks port **8000** when it is free and any free port otherwise,
then opens `http://127.0.0.1:<port>` automatically. Interactive API docs are
at `/docs`. Press `Ctrl+C` in the terminal to stop it.

> The 3D headline pulls Three.js and one typeface from a CDN, so the first
> load needs internet. Everything else — analysis, storage, charts — is
> fully offline. Without WebGL the page degrades gracefully and the whole
> dashboard still works.

---

## 2. Files

| File | Role |
|---|---|
| `app.py` | FastAPI routes, export endpoints, launcher (free-port detection + browser open) |
| `database.py` | SQLite schema, idempotent migration, aggregation queries |
| `analytics.py` | Pure text-analysis engine — no DB, no web framework, unit-testable |
| `templates/index.html` | The entire frontend: gold-on-black UI, Three.js stage, charts |
| `requirements.txt` | Python dependencies |
| `run.bat` / `run.sh` | One-click launchers |
| `counter.db` | SQLite database (created automatically, migrated in place) |

---

## 3. What gets measured

Every entry is analyzed on save; the composer also analyzes live as you type.

**Counts** — characters, characters without spaces, words, unique words,
sentences, lines, paragraphs, syllables.

**Composition** — letters, digits, spaces, punctuation, uppercase, lowercase,
vowels, consonants, emoji-range characters.

**Derived**

| Metric | Definition |
|---|---|
| Average word length | mean characters per word |
| Average sentence length | mean words per sentence |
| Lexical diversity | unique ÷ total words, as a percentage — how repetitive the text is |
| Longest / shortest word | longest and shortest single token |
| Reading time | words ÷ 200 per minute (adult silent reading) |
| Speaking time | words ÷ 130 per minute (comfortable speaking pace) |
| Flesch Reading Ease | `206.835 − 1.015 × (words/sentence) − 84.6 × (syllables/word)`, clamped 0–100 |
| Readability band | Very Easy (80+), Easy (60+), Fairly Hard (50+), Difficult (30+), Very Difficult |
| Keywords | most frequent words after removing a 130-word English stop-word list and tokens under 3 characters |

**Time analytics** — entries per day (zero-filled so the timeline never
breaks), a 24-hour heatmap for any chosen date, a lifetime weekday
distribution, peak hour, peak day, active-day count, and today vs yesterday
change.

---

## 4. API reference

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/` | The dashboard |
| `GET` | `/api/health` | Version and DB status |
| `POST` | `/api/analyze` | Full metrics for a text **without saving** |
| `POST` | `/api/texts` | Analyze + save; returns the stored entry |
| `GET` | `/api/texts` | List entries — `limit`, `search`, `date`, `sort=newest\|oldest\|longest\|words` |
| `GET` | `/api/texts/{id}` | One entry with recomputed metrics and keywords |
| `DELETE` | `/api/texts/{id}` | Delete one entry |
| `DELETE` | `/api/texts?confirm=true` | Delete every entry |
| `GET` | `/api/stats` | Summary KPIs |
| `GET` | `/api/stats/daywise?days=7` | Day-by-day series (1–90 days) |
| `GET` | `/api/stats/hourly?date=YYYY-MM-DD` | 24-slot breakdown |
| `GET` | `/api/stats/weekday` | Lifetime weekday distribution |
| `GET` | `/api/stats/keywords?limit=15` | Corpus-wide keywords |
| `GET` | `/api/stats/overview?days=7` | Everything above in one round-trip |
| `GET` | `/api/export?format=csv\|json` | Download the full table |

Example:
```bash
curl -X POST http://127.0.0.1:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"text":"The quick brown fox jumps over the lazy dog."}'
```

---

## 5. The 3D stage

The headline is genuine extruded geometry, not a CSS trick:

* Each letter is its own extruded, bevelled `TextGeometry` mesh. Glyphs are
  cached, so a letter you have typed before costs nothing to show again, and
  letters are positioned using the typeface's real advance widths rather
  than one fixed gap.
* **The headline is built incrementally.** On every keystroke the new string
  is diffed against what is already on stage: matching letters keep running
  untouched, removed letters spin and fade out, and only genuinely new
  letters are created — each dropping in from behind with a staggered
  ease-out-back. That is why typing looks continuous instead of the whole
  line flickering and rebuilding on each key.
* An **environment map** (a small studio painted into a canvas: warm
  ceiling, two light strips, dark floor) is what makes the metal look like
  metal. A polished surface shows what surrounds it, not its own colour, so
  lamps alone leave a few hot spots on an otherwise black shape. Lamps —
  warm key, cool rim, front fill — sit on top of that.
* Output is ACES-filmic tone-mapped and sRGB-encoded, and material colours
  are converted from sRGB to linear first, otherwise the gold washes out to
  pale silver.
* **Finish** cycles four materials — Polished Gold, Brushed Brass,
  Champagne, Antique Bronze — by repainting the existing letters, so the
  animation never restarts. **Pause spin** eases the rotation to a stop
  rather than snapping.
* If the typeface fails to load, the scene falls back to per-letter extruded
  slabs with canvas-drawn glyph faces, so you always get 3D text.

The headline follows the first line of your input (70 ms debounce),
truncates at a word boundary around 20 characters so long paragraphs do not
shrink the type to nothing, and drops characters the Latin typeface cannot
draw. When the box is empty it shows **JAY MELDI MAA** — change
`DEFAULT_TEXT` near the top of the stage code in `templates/index.html` to
set your own.

---

## 6. Database

Single table, `texts`, one row per entry. `init_db()` is an idempotent
migrator: it creates the table, `ALTER TABLE`s in any metric column added by
a newer version, and back-fills those columns for rows written by an older
build — so an existing `counter.db` upgrades in place with no data loss.
Indexes cover `created_at`, `date_str`, `hour` and `weekday`.

The DB path is resolved relative to `database.py`, so the app works no matter
which directory you launch it from.

---

## 7. Keyboard

| Shortcut | Action |
|---|---|
| `Enter` | Analyze and save the entry |
| `Shift` + `Enter` | Insert a line break instead of saving |

---

## 8. Notes and limits

* Syllable counting is a vowel-group heuristic, so Flesch scores are
  indicative rather than exact — good for comparing your own entries, not
  for formal readability certification.
* Sentence splitting is regex-based and will count `Dr.` or `e.g.` as a
  sentence break.
* The stop-word list is English only; keyword extraction on other languages
  will surface common function words.
* Everything runs on `127.0.0.1` with no authentication — it is a personal
  local tool, not a multi-user service. Do not expose it to a network
  without adding auth.
