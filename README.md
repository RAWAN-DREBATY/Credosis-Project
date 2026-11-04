# Resumable Upload API

A backend service for uploading files over **unreliable internet**. A file is split into small chunks.
If the connection drops, the client asks the server which chunks already arrived and sends only the
missing ones, instead of starting from zero.

Built for the Credosis Internship Program, Phase 02 (Backend track).

## The problem

In my country, electricity and internet are unstable. Uploads fail at 90% and users must start over.
Most apps assume a stable connection. This API is designed to survive weak networks.

## Features

**Core feature**
- Resumable chunked uploads: start, send chunks, check progress, complete.

**Supporting features**
- Idempotent chunk upload: sending the same chunk twice is safe (no duplicates), so retries are safe.
- Integrity checks: per-chunk SHA-256 (`X-Chunk-SHA256`) and optional whole-file SHA-256 on completion.
- Users with API keys (`X-API-Key`): each user only sees their own uploads.
- List, download and delete uploads.

## Tech stack

Python 3.11+, FastAPI, SQLAlchemy 2 (SQLite), Pydantic, pytest. API docs with **Swagger UI** at `/docs`.

## Run it

```bash
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open **http://127.0.0.1:8000/docs** (Swagger UI).

## Data tables

| Table | Main columns |
|-------|--------------|
| `users` | id, name, email (unique), api_key (unique), created_at |
| `uploads` | id, user_id, file_name, total_size, total_chunks, sha256, status (`in_progress`/`completed`), created_at |
| `chunks` | id, upload_id, chunk_number, size, sha256, received_at, **UNIQUE(upload_id, chunk_number)** |

The unique constraint on `chunks` is what makes retries safe, even when two identical requests arrive at the same moment.

## Endpoints

| Method | Path | What it does |
|--------|------|--------------|
| POST | `/users` | Create a user, get an API key |
| GET | `/users/me` | Check my API key |
| POST | `/uploads` | 1. Start an upload |
| GET | `/uploads/{id}` | 2. Progress: received and missing chunks |
| PUT | `/uploads/{id}/chunks/{n}` | 3. Send one chunk (idempotent) |
| POST | `/uploads/{id}/complete` | 4. Assemble and verify the file |
| GET | `/uploads/{id}/download` | Download the finished file |
| GET | `/uploads` | List my uploads |
| DELETE | `/uploads/{id}` | Delete an upload |

## Validation and error handling

| Situation | Response |
|-----------|----------|
| Missing / wrong API key | 401 |
| Someone else's upload, or unknown id | 404 (ids don't leak) |
| Bad input (empty name, `../` in file name, zero size, too many chunks, invalid email) | 422 |
| Chunk number out of range, empty chunk, chunk too large, checksum mismatch | 400 |
| Same chunk number sent again with **different** data | 409 |
| Complete while chunks are missing (lists which) | 409 |
| Upload already completed (new chunks) | 409 |
| Assembled file doesn't match declared size/hash | 422 |
| Duplicate email | 409 |

## Try it with a bad network

```bash
uvicorn app.main:app          # terminal 1
python demo_client.py         # terminal 2
```

`demo_client.py` simulates a network that randomly drops requests (even *after* the server received the chunk,
so the client doesn't know). It retries, then asks the server what is missing, sends only that, and finally
checks the downloaded file is identical to the original.

## Tests

```bash
pytest
```

19 tests cover: resume after a dropped connection, idempotent retries, checksum failures, validation,
ownership between users, completion rules and cleanup.

## Project structure

```
app/
  main.py          FastAPI app, Swagger description
  config.py        settings and limits
  database.py      engine and session
  models.py        users, uploads, chunks tables
  schemas.py       request/response validation (Pydantic)
  auth.py          X-API-Key authentication
  storage.py       atomic chunk writes, file assembly
  routers/
    users.py
    uploads.py
tests/             pytest suite
demo_client.py     bad-network simulation
```

## Limitations and next steps

- SQLite and local disk are fine for a demo; production would use PostgreSQL and object storage (S3).
- API keys are simple; real systems would add hashed keys or OAuth/JWT.
- No rate limiting or cleanup job for abandoned uploads yet.
