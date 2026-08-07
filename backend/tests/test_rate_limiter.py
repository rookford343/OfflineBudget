from backend.services.rate_limiter import allow, _reset_for_tests


def setup_function():
    _reset_for_tests()


def test_allows_up_to_the_limit():
    for _ in range(5):
        assert allow("alice", limit=5, window_seconds=3600) is True


def test_blocks_once_limit_exceeded():
    for _ in range(5):
        allow("alice", limit=5, window_seconds=3600)
    assert allow("alice", limit=5, window_seconds=3600) is False


def test_keys_are_isolated():
    for _ in range(5):
        allow("alice", limit=5, window_seconds=3600)
    assert allow("bob", limit=5, window_seconds=3600) is True


def test_window_expiry_resets_the_limit(monkeypatch):
    import backend.services.rate_limiter as rl

    t = [1000.0]
    monkeypatch.setattr(rl.time, "time", lambda: t[0])

    for _ in range(5):
        assert allow("alice", limit=5, window_seconds=60) is True
    assert allow("alice", limit=5, window_seconds=60) is False

    t[0] += 61  # advance past the window
    assert allow("alice", limit=5, window_seconds=60) is True
