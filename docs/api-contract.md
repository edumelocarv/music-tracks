# API contract (complements spec §11)

JSON shapes shared by backend and frontend. Booleans are real JSON booleans (DB 0/1 converted). Times are ISO 8601 UTC strings. All routes are under `/api`.

## Objects

**Job**
```json
{"id": "uuid", "song_id": "uuid", "song_title": "str", "stem_mode": 4,
 "status": "queued|running|done|failed|canceled",
 "step": "download|prepare|separate|analyze|peaks|null", "step_detail": "downloading_model|null",
 "step_index": 2, "step_count": 4, "step_progress": 45,
 "error_code": "str|null", "error_detail": "str|null", "attempts": 1,
 "created_at": "...", "started_at": "...|null", "finished_at": "...|null"}
```

**Song**
```json
{"id": "uuid", "title": "str", "artist": "str|null", "album": "str|null", "duration_s": 241.3,
 "source_type": "file|url|watch", "source_url": "str|null", "original_filename": "str|null",
 "stem_mode": 4, "status": "pending|processing|ready|failed",
 "favorite": false, "notes": "", "has_cover": true,
 "cover_url": "/api/songs/<id>/cover?v=<updated_at>|null",
 "bpm": 120.0, "key_label": "A minor|null", "analysis_status": "none|ok|failed",
 "player_state": {}, "tags": ["estudar"],
 "stems": ["vocals", "drums", "bass", "other"],
 "active_job": "Job|null", "last_job": "Job|null",
 "created_at": "...", "updated_at": "..."}
```
- `stems` = stems of `stem_mode` in glossary order when `songs/<id>/stems/` has files; otherwise `[]`.
- `active_job` = the queued/running job, if any. `last_job` = most recent job by `created_at` (may equal active_job).
- `GET /songs` returns `{"songs": [Song, ...]}` with the same shape (including jobs, tags).

**Marker**: `{"id", "song_id", "kind": "marker|loop", "name", "start_s", "end_s": "number|null", "created_at"}`

**Settings**: `{"language": "en|pt-BR|null", "default_stem_mode": 2|4|6, "metronome_volume": 0-100, "data_dir": "/abs/path (configured value)", "data_dir_locked": bool, "restart_required": bool}` — `restart_required` is true when the configured `data_dir` differs from the one the running server uses.

**Health**: `{"ok": true, "device": "mps|cpu", "ffmpeg": "8.1.2", "yt_dlp": "2026.10.26", "data_dir": "...", "models_cached": bool}`

**Error**: `{"error": {"code": "DUPLICATE", "detail": "...", "existing_song_id": "..."}}` (extra keys per code).

## Endpoints → responses

| Route | Request | Response |
|---|---|---|
| `GET /health` | | Health |
| `GET /songs` | query: q, tag, favorite (true/false), status, sort, order | `{songs: [Song]}` |
| `POST /songs/upload` | multipart: `file`, `stem_mode` (form field, "2"/"4"/"6"; default = setting) | 201 `{song: Song, job: Job}` |
| `POST /songs/url` | `{url, stem_mode?}` | 201 `{song, job}` |
| `GET /songs/{id}` | | Song |
| `PATCH /songs/{id}` | partial `{title?, artist?, album?, favorite?, notes?, tags?, player_state?}` | Song |
| `DELETE /songs/{id}` | | 204 |
| `PUT /songs/{id}/cover` | multipart `file` | Song |
| `GET /songs/{id}/cover` | | image/jpeg or 404 |
| `DELETE /songs/{id}/cover` | | Song |
| `POST /songs/{id}/reprocess` | `{stem_mode}` | 201 `{job: Job}` |
| `GET /songs/{id}/stems/{stem}.flac` | | audio/flac |
| `GET /songs/{id}/peaks` | | peaks.json (spec §7.5) |
| `GET /songs/{id}/analysis` | | analysis.json (spec §7.4) |
| `GET /songs/{id}/markers` | | `{markers: [Marker]}` sorted by start_s |
| `POST /songs/{id}/markers` | `{kind, name, start_s, end_s?}` | 201 Marker |
| `PATCH /songs/{id}/markers/{mid}` | partial `{name?, start_s?, end_s?}` | Marker |
| `DELETE /songs/{id}/markers/{mid}` | | 204 |
| `GET /songs/{id}/export/stem/{stem}?format=` | | file download |
| `GET /songs/{id}/export/zip?format=` | | application/zip download |
| `POST /songs/{id}/export/mix` | `{gains, speed, semitones, start_s, end_s, format}` | file download |
| `GET /jobs?limit=20` | | `{jobs: [Job]}` active first (created_at asc), then finished (finished_at desc) |
| `POST /jobs/{id}/cancel` | | Job |
| `POST /jobs/{id}/retry` | | 201 `{job: Job}` |
| `GET /tags` | | `{tags: [{name, count}]}` sorted by name |
| `GET /settings` / `PUT /settings` | partial Settings (minus read-only fields) | Settings |

Downloads use `Content-Disposition: attachment; filename="<ascii fallback>"; filename*=UTF-8''<percent-encoded>`.
