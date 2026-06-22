from dexport.ratelimit import RateLimiter, route_key


def test_route_key_masks_ids():
    assert route_key("GET", "/channels/123456789012345678/messages?limit=100") == (
        "GET /channels/{id}/messages"
    )
    assert (
        route_key(
            "put",
            "/channels/111111111111111111/messages/222222222222222222/reactions/x/@me",
        )
        == "PUT /channels/{id}/messages/{id}/reactions/x/@me"
    )


def _limiter(now_ref):
    sleeps = []
    return (
        RateLimiter(
            floor_min=0.0,
            floor_max=0.0,
            clock=lambda: now_ref[0],
            sleeper=lambda s: sleeps.append(s),
            jitter=lambda a, b: 0.0,
        ),
        sleeps,
    )


def test_floor_delay_applied():
    now = [0.0]
    sleeps = []
    rl = RateLimiter(
        floor_min=0.3,
        floor_max=0.3,
        clock=lambda: now[0],
        sleeper=lambda s: sleeps.append(s),
        jitter=lambda a, b: 0.3,
    )
    rl.acquire("GET /x")
    assert sleeps == [0.3]


def test_acquire_waits_when_route_exhausted():
    now = [0.0]
    rl, sleeps = _limiter(now)
    rl.update("GET /x", {"x-ratelimit-remaining": "0", "x-ratelimit-reset-after": "5"})
    rl.acquire("GET /x")
    assert 5.0 in sleeps  # slept until reset


def test_acquire_no_wait_when_budget_left():
    now = [0.0]
    rl, sleeps = _limiter(now)
    rl.update("GET /x", {"x-ratelimit-remaining": "3", "x-ratelimit-reset-after": "5"})
    rl.acquire("GET /x")
    assert sleeps == []
