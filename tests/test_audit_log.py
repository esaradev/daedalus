"""AuditLog: append-only spend-decision trail."""

from daedalus.audit_log import AuditLog


def _log(tmp_path):
    return AuditLog(tmp_path / "decisions.log")


def test_record_and_read(tmp_path):
    log = _log(tmp_path)
    log.record(action="spend", vendor="openrouter", amount_cents=456,
               allowed=True, protection="ok", reason="authorized")
    entries = log.entries()
    assert len(entries) == 1
    assert entries[0]["vendor"] == "openrouter" and entries[0]["allowed"] is True


def test_append_only(tmp_path):
    log = _log(tmp_path)
    log.record(action="spend", vendor="a", amount_cents=1, allowed=True, protection="ok", reason="x")
    log.record(action="spend", vendor="b", amount_cents=2, allowed=False, protection="egress", reason="y")
    assert len(log.entries()) == 2


def test_count_blocked(tmp_path):
    log = _log(tmp_path)
    log.record(action="spend", vendor="a", amount_cents=1, allowed=True, protection="ok", reason="x")
    log.record(action="spend", vendor="b", amount_cents=2, allowed=False, protection="egress", reason="y")
    log.record(action="spend", vendor="c", amount_cents=3, allowed=False, protection="economics", reason="z")
    assert log.count_blocked() == 2


def test_recent_newest_first(tmp_path):
    log = _log(tmp_path)
    for i in range(5):
        log.record(action="spend", vendor=str(i), amount_cents=i + 1,
                   allowed=True, protection="ok", reason="x")
    recent = log.recent(3)
    assert [e["vendor"] for e in recent] == ["4", "3", "2"]


def test_empty_log(tmp_path):
    assert _log(tmp_path).entries() == []
