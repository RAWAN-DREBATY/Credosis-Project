from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import config
from .database import Base, engine
from .routers import uploads, users

DESCRIPTION = """
**Resumable Upload API** – built for places where electricity and internet are unreliable.

A big file is split into small *chunks*. If the connection drops, the client asks the server
which chunks already arrived and continues from there, instead of starting from zero.

### How to try it in Swagger
1. `POST /users` – create a user and copy the `api_key`.
2. Click **Authorize** (top right) and paste the key.
3. `POST /uploads` – start an upload.
4. `PUT /uploads/{id}/chunks/{n}` – send chunks (sending the same chunk twice is safe).
5. `GET /uploads/{id}` – see what is missing.
6. `POST /uploads/{id}/complete` – assemble the file.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)
    yield


app = FastAPI(
    title="Resumable Upload API",
    description=DESCRIPTION,
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(users.router)
app.include_router(uploads.router)


@app.get("/", tags=["Health"], summary="Health check")
def root():
    return {"status": "ok", "docs": "/docs"}
