from datetime import datetime, timedelta, timezone
import os
import random
import string

from locust import HttpUser, between, task


def _rand_url() -> str:
    suffix = "".join(random.choice(string.ascii_lowercase) for _ in range(10))
    return f"https://example.com/{suffix}"


class UrlShortenerUser(HttpUser):
    wait_time = between(0.01, 0.2)

    def on_start(self):
        self.token = None
        email = f"load_{random.randint(1, 10_000_000)}@example.com"
        password = "secret"

        # Best-effort: register and login (service allows guests too)
        self.client.post("/auth/register", json={"email": email, "password": password}, name="/auth/register")
        r = self.client.post(
            "/auth/token",
            data={"username": email, "password": password},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            name="/auth/token",
        )
        if r.status_code == 200:
            self.token = r.json().get("access_token")

    @task(6)
    def create_links_mass(self):
        payload = {"original_url": _rand_url()}
        # Some links with TTL to exercise cleanup paths
        if random.random() < 0.1:
            payload["expires_at"] = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()

        headers = {"Authorization": f"Bearer {self.token}"} if self.token and random.random() < 0.8 else {}
        r = self.client.post("/links/shorten", json=payload, headers=headers, name="/links/shorten")
        if r.status_code == 200:
            self.short_code = r.json().get("short_code")

    @task(4)
    def redirect_hot_links(self):
        code = getattr(self, "short_code", None)
        if code:
            self.client.get(f"/{code}", allow_redirects=False, name="/{short_code}")

    @task(2)
    def stats(self):
        code = getattr(self, "short_code", None)
        if code:
            self.client.get(f"/links/{code}/stats", name="/links/{short_code}/stats")

