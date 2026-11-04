import hashlib

from conftest import make_user

OCTET = {"Content-Type": "application/octet-stream"}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def start_upload(client, auth, data: bytes, chunk_size: int, name="file.bin"):
    chunks = [data[i : i + chunk_size] for i in range(0, len(data), chunk_size)]
    r = client.post(
        "/uploads",
        headers=auth,
        json={
            "file_name": name,
            "total_size": len(data),
            "total_chunks": len(chunks),
            "sha256": sha(data),
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"], chunks


def put_chunk(client, auth, upload_id, n, chunk, **extra_headers):
    return client.put(
        f"/uploads/{upload_id}/chunks/{n}",
        headers={**auth, **OCTET, **extra_headers},
        content=chunk,
    )


# ---------------- users & auth ----------------
def test_create_user_returns_api_key(client):
    user = make_user(client)
    assert len(user["api_key"]) == 48


def test_duplicate_email_is_409(client):
    make_user(client)
    r = client.post("/users", json={"name": "Other", "email": "RAWAN@example.com"})
    assert r.status_code == 409


def test_invalid_email_is_422(client):
    r = client.post("/users", json={"name": "A", "email": "not-an-email"})
    assert r.status_code == 422


def test_missing_and_wrong_api_key_is_401(client):
    assert client.get("/uploads").status_code == 401
    assert client.get("/uploads", headers={"X-API-Key": "wrong"}).status_code == 401


# ---------------- validation ----------------
def test_create_upload_validation(client, auth):
    bad_payloads = [
        {"file_name": "../etc/passwd", "total_size": 10, "total_chunks": 1},  # path trick
        {"file_name": "a.bin", "total_size": 0, "total_chunks": 1},
        {"file_name": "a.bin", "total_size": 10, "total_chunks": 0},
        {"file_name": "a.bin", "total_size": 2, "total_chunks": 5},  # more chunks than bytes
        {"file_name": "a.bin", "total_size": 10**10, "total_chunks": 5},  # too big
    ]
    for p in bad_payloads:
        r = client.post("/uploads", headers=auth, json=p)
        assert r.status_code == 422, (p, r.text)


def test_chunk_number_out_of_range_is_400(client, auth):
    upload_id, chunks = start_upload(client, auth, b"abcdef", 3)
    assert put_chunk(client, auth, upload_id, 2, b"abc").status_code == 400


def test_empty_chunk_is_rejected(client, auth):
    upload_id, _ = start_upload(client, auth, b"abcdef", 3)
    assert put_chunk(client, auth, upload_id, 0, b"").status_code in (400, 422)


def test_checksum_mismatch_is_400(client, auth):
    upload_id, chunks = start_upload(client, auth, b"abcdef", 3)
    r = put_chunk(client, auth, upload_id, 0, chunks[0], **{"X-Chunk-SHA256": "0" * 64})
    assert r.status_code == 400
    # and nothing was stored
    assert client.get(f"/uploads/{upload_id}", headers=auth).json()["received_chunks"] == []


def test_correct_checksum_is_accepted(client, auth):
    upload_id, chunks = start_upload(client, auth, b"abcdef", 3)
    r = put_chunk(client, auth, upload_id, 0, chunks[0], **{"X-Chunk-SHA256": sha(chunks[0])})
    assert r.status_code == 200


# ---------------- the core idea: resume + idempotency ----------------
def test_resume_after_dropped_connection(client, auth):
    data = bytes(range(256)) * 40  # 10,240 bytes
    upload_id, chunks = start_upload(client, auth, data, 1024)  # 10 chunks
    assert len(chunks) == 10

    # connection "drops" after chunks 0..3 and chunk 6 arrived
    for n in (0, 1, 2, 3, 6):
        assert put_chunk(client, auth, upload_id, n, chunks[n]).status_code == 200

    st = client.get(f"/uploads/{upload_id}", headers=auth).json()
    assert st["received_chunks"] == [0, 1, 2, 3, 6]
    assert st["missing_chunks"] == [4, 5, 7, 8, 9]
    assert st["progress_percent"] == 50.0

    # client resumes: only sends what is missing
    for n in st["missing_chunks"]:
        assert put_chunk(client, auth, upload_id, n, chunks[n]).status_code == 200

    done = client.post(f"/uploads/{upload_id}/complete", headers=auth)
    assert done.status_code == 200
    assert done.json()["status"] == "completed"

    downloaded = client.get(f"/uploads/{upload_id}/download", headers=auth)
    assert downloaded.status_code == 200
    assert downloaded.content == data  # byte-for-byte identical


def test_sending_same_chunk_twice_is_safe(client, auth):
    upload_id, chunks = start_upload(client, auth, b"abcdef", 3)
    first = put_chunk(client, auth, upload_id, 0, chunks[0]).json()
    second = put_chunk(client, auth, upload_id, 0, chunks[0]).json()
    assert first["already_received"] is False
    assert second["already_received"] is True
    assert second["received_count"] == 1  # no duplicate row


def test_same_chunk_number_different_data_is_409(client, auth):
    upload_id, _ = start_upload(client, auth, b"abcdef", 3)
    assert put_chunk(client, auth, upload_id, 0, b"abc").status_code == 200
    assert put_chunk(client, auth, upload_id, 0, b"XYZ").status_code == 409


def test_complete_with_missing_chunks_is_409(client, auth):
    upload_id, chunks = start_upload(client, auth, b"abcdef", 3)
    put_chunk(client, auth, upload_id, 0, chunks[0])
    r = client.post(f"/uploads/{upload_id}/complete", headers=auth)
    assert r.status_code == 409
    assert "missing" in r.json()["detail"]


def test_complete_twice_is_safe_and_no_more_chunks_after(client, auth):
    upload_id, chunks = start_upload(client, auth, b"abcdef", 3)
    for n, c in enumerate(chunks):
        put_chunk(client, auth, upload_id, n, c)
    assert client.post(f"/uploads/{upload_id}/complete", headers=auth).status_code == 200
    assert client.post(f"/uploads/{upload_id}/complete", headers=auth).status_code == 200
    assert put_chunk(client, auth, upload_id, 0, chunks[0]).status_code == 409


def test_wrong_declared_hash_is_rejected_on_complete(client, auth):
    data = b"abcdef"
    r = client.post(
        "/uploads",
        headers=auth,
        json={"file_name": "x.bin", "total_size": 6, "total_chunks": 2, "sha256": "a" * 64},
    )
    upload_id = r.json()["id"]
    put_chunk(client, auth, upload_id, 0, data[:3])
    put_chunk(client, auth, upload_id, 1, data[3:])
    assert client.post(f"/uploads/{upload_id}/complete", headers=auth).status_code == 422


def test_download_before_complete_is_409(client, auth):
    upload_id, _ = start_upload(client, auth, b"abcdef", 3)
    assert client.get(f"/uploads/{upload_id}/download", headers=auth).status_code == 409


# ---------------- ownership & cleanup ----------------
def test_users_cannot_see_each_others_uploads(client, auth):
    upload_id, _ = start_upload(client, auth, b"abcdef", 3)
    other = make_user(client, "Other", "other@example.com")
    h2 = {"X-API-Key": other["api_key"]}
    assert client.get(f"/uploads/{upload_id}", headers=h2).status_code == 404
    assert put_chunk(client, h2, upload_id, 0, b"abc").status_code == 404
    assert client.get("/uploads", headers=h2).json() == []


def test_unknown_upload_is_404(client, auth):
    assert client.get("/uploads/9999", headers=auth).status_code == 404


def test_list_and_delete(client, auth):
    upload_id, _ = start_upload(client, auth, b"abcdef", 3)
    assert len(client.get("/uploads", headers=auth).json()) == 1
    assert client.delete(f"/uploads/{upload_id}", headers=auth).status_code == 204
    assert client.get(f"/uploads/{upload_id}", headers=auth).status_code == 404
    assert client.get("/uploads", headers=auth).json() == []
