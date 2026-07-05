"""Rate-limit client identity and password policy (FoodAssistant-ovyu)."""
from types import SimpleNamespace

from app import ratelimit
from app.deps import client_ip
from app.security import MIN_PASSWORD_LENGTH, password_problem


def _req(xff=None, peer="10.0.0.1"):
    headers = {"x-forwarded-for": xff} if xff is not None else {}
    return SimpleNamespace(headers=headers,
                           client=SimpleNamespace(host=peer) if peer else None)


def test_client_ip_uses_the_proxy_appended_entry():
    # Caddy appends the true client, so the rightmost entry is trustworthy;
    # a spoofed leftmost value must not be what we rate-limit on.
    assert client_ip(_req(xff="1.2.3.4")) == "1.2.3.4"
    assert client_ip(_req(xff="9.9.9.9, 1.2.3.4")) == "1.2.3.4"
    assert client_ip(_req(xff="spoofed, real-client")) == "real-client"


def test_client_ip_falls_back_to_peer_without_header():
    assert client_ip(_req(xff=None, peer="10.0.0.5")) == "10.0.0.5"
    assert client_ip(_req(xff="", peer="10.0.0.6")) == "10.0.0.6"
    assert client_ip(_req(xff=None, peer=None)) == "unknown"


def test_two_clients_get_independent_rate_windows():
    # The bug this guards: behind a proxy every request looked like one IP,
    # so one client's attempts throttled everyone. Distinct IPs must not.
    ratelimit.reset()
    assert ratelimit.allow("login:1.2.3.4", 1) is True
    assert ratelimit.allow("login:1.2.3.4", 1) is False   # same client capped
    assert ratelimit.allow("login:5.6.7.8", 1) is True    # different client free


def test_password_problem_rejects_short_common_and_email():
    assert password_problem("short1") is not None
    assert password_problem("x" * (MIN_PASSWORD_LENGTH - 1)) is not None
    assert password_problem("password123") is not None      # common
    assert password_problem("PassWord123") is not None      # common, case-insensitive
    assert password_problem("dan@example.com", "dan@example.com") is not None
    # A decent password passes.
    assert password_problem("k7-mango-lantern", "dan@example.com") is None


def test_signup_enforces_the_policy(client):
    weak = client.post("/v1/accounts/signup",
                       json={"email": "new@example.com", "password": "password123"})
    assert weak.status_code == 400
    short = client.post("/v1/accounts/signup",
                        json={"email": "new@example.com", "password": "short12"})
    assert short.status_code == 400
    ok = client.post("/v1/accounts/signup",
                     json={"email": "new@example.com", "password": "k7-mango-lantern"})
    assert ok.status_code == 200
