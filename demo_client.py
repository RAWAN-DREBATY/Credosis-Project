"""
Demo client: uploads a file over a FAKE BAD NETWORK to show resumable uploads.

The network randomly "drops" requests. The client:
  1. retries a failed chunk a few times, and
  2. if it gives up (connection really dead), it later asks the server
     GET /uploads/{id} which chunks arrived and sends ONLY the missing ones.

Run the API first:   uvicorn app.main:app
Then:                python demo_client.py
"""
import hashlib
import os
import random
import sys
import time

import requests

BASE = os.getenv("API_URL", "http://127.0.0.1:8000")
CHUNK_SIZE = 64 * 1024        # 64 KB chunks
FILE_SIZE = 1024 * 1024       # 1 MB demo file -> 16 chunks
DROP_RATE = 0.35              # 35% of requests "fail"
MAX_RETRIES = 2


class NetworkDropped(Exception):
    pass


def flaky(func, *args, **kwargs):
    """Randomly fail BEFORE or AFTER the request reaches the server (both happen in real life)."""
    if random.random() < DROP_RATE / 2:
        raise NetworkDropped("dropped before reaching the server")
    resp = func(*args, **kwargs)
    if random.random() < DROP_RATE / 2:
        raise NetworkDropped("server got it, but the answer was lost")  # a retry must be safe!
    return resp


def log(msg):
    print(msg, flush=True)


def main():
    random.seed(int(sys.argv[1]) if len(sys.argv) > 1 else 7)

    # --- create a user and a random file ---
    user = requests.post(
        f"{BASE}/users",
        json={"name": "Demo", "email": f"demo{int(time.time())}@example.com"},
    ).json()
    headers = {"X-API-Key": user["api_key"]}
    data = os.urandom(FILE_SIZE)
    chunks = [data[i : i + CHUNK_SIZE] for i in range(0, len(data), CHUNK_SIZE)]
    log(f"File: {len(data)} bytes in {len(chunks)} chunks. Network drop rate: {int(DROP_RATE*100)}%\n")

    upload = requests.post(
        f"{BASE}/uploads",
        headers=headers,
        json={
            "file_name": "demo.bin",
            "total_size": len(data),
            "total_chunks": len(chunks),
            "sha256": hashlib.sha256(data).hexdigest(),
        },
    ).json()
    uid = upload["id"]

    def send(n):
        return requests.put(
            f"{BASE}/uploads/{uid}/chunks/{n}",
            headers={**headers, "Content-Type": "application/octet-stream"},
            data=chunks[n],
        )

    pending = list(range(len(chunks)))
    round_no = 0
    while pending:
        round_no += 1
        log(f"--- Round {round_no}: trying to send {len(pending)} chunk(s) ---")
        for n in pending:
            for attempt in range(1, MAX_RETRIES + 2):
                try:
                    r = flaky(send, n)
                    tag = "(already had it - safe retry)" if r.json()["already_received"] else ""
                    log(f"  chunk {n:2d}: OK {tag}")
                    break
                except NetworkDropped as e:
                    log(f"  chunk {n:2d}: attempt {attempt} failed - {e}")
            else:
                log(f"  chunk {n:2d}: giving up for now")
        # RESUME: ask the server what it really has, instead of trusting our own memory
        st = requests.get(f"{BASE}/uploads/{uid}", headers=headers).json()
        pending = st["missing_chunks"]
        log(f"  server says: {st['progress_percent']}% done, missing: {pending}\n")

    done = requests.post(f"{BASE}/uploads/{uid}/complete", headers=headers).json()
    log(f"Complete -> status: {done['status']}")

    back = requests.get(f"{BASE}/uploads/{uid}/download", headers=headers).content
    ok = hashlib.sha256(back).hexdigest() == hashlib.sha256(data).hexdigest()
    log(f"Downloaded file identical to original: {ok}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
