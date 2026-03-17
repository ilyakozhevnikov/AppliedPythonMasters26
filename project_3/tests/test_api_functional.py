from datetime import datetime, timedelta, timezone

import httpx
import pytest


@pytest.fixture()
async def client(app_module, db, fake_redis):
    transport = httpx.ASGITransport(app=app_module.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def register_and_login(
    client: httpx.AsyncClient,
    email: str = "user@example.com",
    password: str = "secret",
) -> str:
    r = await client.post("/auth/register", json={"email": email, "password": password})
    assert r.status_code == 200, r.text

    r = await client.post("/auth/token", data={"username": email, "password": password})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    assert token
    return token


def auth_headers(token: str):
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.anyio
async def test_register_duplicate_email(client):
    r1 = await client.post("/auth/register", json={"email": "a@a.com", "password": "x"})
    assert r1.status_code == 200
    r2 = await client.post("/auth/register", json={"email": "a@a.com", "password": "x"})
    assert r2.status_code == 400


@pytest.mark.anyio
async def test_login_wrong_password(client):
    await client.post("/auth/register", json={"email": "u@e.com", "password": "right"})
    r = await client.post("/auth/token", data={"username": "u@e.com", "password": "wrong"})
    assert r.status_code == 400


@pytest.mark.anyio
async def test_create_short_link_guest_and_redirect_increments_stats(client, app_module):
    r = await client.post("/links/shorten", json={"original_url": "https://example.org"})
    assert r.status_code == 200, r.text
    short_code = r.json()["short_code"]

    assert app_module.redis_client.get(app_module.cache_key_for_short_code(short_code)) in {
        "https://example.org",
        "https://example.org/",
    }

    r = await client.get(f"/{short_code}", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] in {"https://example.org", "https://example.org/"}

    r = await client.get(f"/links/{short_code}/stats")
    assert r.status_code == 200
    payload = r.json()
    assert payload["original_url"] in {"https://example.org", "https://example.org/"}
    assert payload["click_count"] == 1
    assert payload["last_accessed_at"] is not None


@pytest.mark.anyio
async def test_create_short_link_custom_alias_uniqueness(client):
    r1 = await client.post(
        "/links/shorten",
        json={"original_url": "https://example.com/1", "custom_alias": "myalias"},
    )
    assert r1.status_code == 200, r1.text
    assert r1.json()["short_code"] == "myalias"

    r2 = await client.post(
        "/links/shorten",
        json={"original_url": "https://example.com/2", "custom_alias": "myalias"},
    )
    assert r2.status_code == 400


@pytest.mark.anyio
async def test_create_short_link_invalid_url(client):
    r = await client.post("/links/shorten", json={"original_url": "not a url"})
    assert r.status_code == 422


@pytest.mark.anyio
async def test_expires_at_past_causes_404_on_redirect_and_moves_to_history(client, app_module):
    past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    r = await client.post("/links/shorten", json={"original_url": "https://will.expire", "expires_at": past})
    assert r.status_code == 200
    short_code = r.json()["short_code"]

    r = await client.get(f"/{short_code}", follow_redirects=False)
    assert r.status_code == 404

    s = app_module.SessionLocal()
    try:
        assert s.query(app_module.Link).filter(app_module.Link.short_code == short_code).first() is None
        assert (
            s.query(app_module.ExpiredLinkHistory)
            .filter(app_module.ExpiredLinkHistory.short_code == short_code)
            .first()
            is not None
        )
    finally:
        s.close()


@pytest.mark.anyio
async def test_update_and_delete_require_owner(client):
    token_owner = await register_and_login(client, email="owner@e.com")
    token_other = await register_and_login(client, email="other@e.com")

    r = await client.post(
        "/links/shorten",
        json={"original_url": "https://example.com/a"},
        headers=auth_headers(token_owner),
    )
    assert r.status_code == 200, r.text
    code = r.json()["short_code"]

    r = await client.put(
        f"/links/{code}",
        json={"new_original_url": "https://example.com/b"},
        headers=auth_headers(token_other),
    )
    assert r.status_code == 403
    r = await client.delete(f"/links/{code}", headers=auth_headers(token_other))
    assert r.status_code == 403

    r = await client.put(
        f"/links/{code}",
        json={"new_original_url": "https://example.com/b"},
        headers=auth_headers(token_owner),
    )
    assert r.status_code == 200, r.text
    assert r.json()["original_url"] == "https://example.com/b"

    r = await client.put(
        f"/links/{code}",
        json={"new_short_code": "newcode1"},
        headers=auth_headers(token_owner),
    )
    assert r.status_code == 200, r.text
    assert r.json()["short_code"] == "newcode1"

    r = await client.delete("/links/newcode1", headers=auth_headers(token_owner))
    assert r.status_code == 204


@pytest.mark.anyio
async def test_search_by_original_url_returns_only_users_links(client):
    token = await register_and_login(client, email="s@e.com")
    headers = auth_headers(token)

    r1 = await client.post("/links/shorten", json={"original_url": "https://q.com/"}, headers=headers)
    r2 = await client.post("/links/shorten", json={"original_url": "https://q.com/"}, headers=headers)
    assert r1.status_code == 200 and r2.status_code == 200

    await client.post("/links/shorten", json={"original_url": "https://q.com/"})

    r = await client.get("/links/search", params={"original_url": "https://q.com/"}, headers=headers)
    assert r.status_code == 200
    codes = {x["short_code"] for x in r.json()}
    assert r1.json()["short_code"] in codes
    assert r2.json()["short_code"] in codes
    assert len(codes) == 2


@pytest.mark.anyio
async def test_projects_create_and_list_links(client):
    token = await register_and_login(client, email="p@e.com")
    headers = auth_headers(token)

    r = await client.post("/projects", params={"name": "proj1"}, headers=headers)
    assert r.status_code == 200, r.text
    project_id = r.json()["id"]

    r = await client.post(
        "/links/shorten",
        json={"original_url": "https://in.project", "project_id": project_id},
        headers=headers,
    )
    assert r.status_code == 200
    code = r.json()["short_code"]

    r = await client.get(f"/projects/{project_id}/links", headers=headers)
    assert r.status_code == 200
    assert [x["short_code"] for x in r.json()] == [code]


@pytest.mark.anyio
async def test_stats_cached_path(client, app_module):
    r = await client.post("/links/shorten", json={"original_url": "https://cached.stats"})
    assert r.status_code == 200
    code = r.json()["short_code"]

    r1 = await client.get(f"/links/{code}/stats")
    assert r1.status_code == 200
    assert app_module.redis_client.hgetall(app_module.cache_key_for_stats(code)) != {}

    r2 = await client.get(f"/links/{code}/stats")
    assert r2.status_code == 200
    assert r2.json() == r1.json()

