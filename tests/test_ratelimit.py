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


def test_note_429_global_blocks_all():
    now = [0.0]
    rl, sleeps = _limiter(now)
    retry = rl.note_429({"x-ratelimit-global": "true"}, {"retry_after": 2.0, "global": True})
    assert retry == 2.0
    rl.acquire("GET /anything")
    assert 2.0 in sleeps


def test_note_429_body_retry_after():
    now = [0.0]
    rl, _ = _limiter(now)
    assert rl.note_429({}, {"retry_after": 1.25}) == 1.25


def test_penalize_forces_route_wait():
    now = [0.0]
    rl, sleeps = _limiter(now)
    rl.penalize("POST /y", 3.0)
    rl.acquire("POST /y")
    assert 3.0 in sleeps


def test_note_429_penalizes_route_when_key_given():
    now = [0.0]
    rl, sleeps = _limiter(now)
    rl.note_429({}, {"retry_after": 4.0}, key="POST /z")
    rl.acquire("POST /z")
    assert 4.0 in sleeps
