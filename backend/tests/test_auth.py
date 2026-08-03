import uuid

from httpx import AsyncClient


def _unique_email() -> str:
    return f"test-{uuid.uuid4().hex[:12]}@example.com"


async def test_signup_login_me_flow(client: AsyncClient) -> None:
    email = _unique_email()
    password = "correct horse battery staple"

    signup_response = await client.post("/auth/signup", json={"email": email, "password": password})
    assert signup_response.status_code == 201
    signup_tokens = signup_response.json()
    assert "access_token" in signup_tokens
    assert "refresh_token" in signup_tokens

    login_response = await client.post("/auth/login", json={"email": email, "password": password})
    assert login_response.status_code == 200
    tokens = login_response.json()

    me_response = await client.get(
        "/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert me_response.status_code == 200
    assert me_response.json()["email"] == email


async def test_signup_duplicate_email_rejected(client: AsyncClient) -> None:
    email = _unique_email()
    password = "correct horse battery staple"

    first = await client.post("/auth/signup", json={"email": email, "password": password})
    assert first.status_code == 201

    second = await client.post("/auth/signup", json={"email": email, "password": password})
    assert second.status_code == 409


async def test_login_wrong_password_rejected(client: AsyncClient) -> None:
    email = _unique_email()
    await client.post(
        "/auth/signup", json={"email": email, "password": "correct horse battery staple"}
    )

    response = await client.post("/auth/login", json={"email": email, "password": "wrong password"})
    assert response.status_code == 401


async def test_refresh_issues_new_access_token(client: AsyncClient) -> None:
    email = _unique_email()
    signup_response = await client.post(
        "/auth/signup", json={"email": email, "password": "correct horse battery staple"}
    )
    refresh_token = signup_response.json()["refresh_token"]

    refresh_response = await client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert refresh_response.status_code == 200
    assert "access_token" in refresh_response.json()


async def test_refresh_token_rejected_at_me_endpoint(client: AsyncClient) -> None:
    email = _unique_email()
    signup_response = await client.post(
        "/auth/signup", json={"email": email, "password": "correct horse battery staple"}
    )
    refresh_token = signup_response.json()["refresh_token"]

    response = await client.get("/auth/me", headers={"Authorization": f"Bearer {refresh_token}"})
    assert response.status_code == 401


async def test_me_without_token_rejected(client: AsyncClient) -> None:
    response = await client.get("/auth/me")
    assert response.status_code in (401, 403)
