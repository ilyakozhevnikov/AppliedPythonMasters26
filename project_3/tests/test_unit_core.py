from datetime import datetime, timedelta, timezone

import pytest


def test_generate_short_code_basic(app_module):
    code = app_module.generate_short_code()
    assert isinstance(code, str)
    assert len(code) == 8
    assert all(ch in app_module.ALPHABET for ch in code)


def test_ensure_unique_short_code_custom_alias_conflict(app_module, db):
    link = app_module.Link(short_code="alias1", original_url="https://example.com")
    db.add(link)
    db.commit()

    with pytest.raises(app_module.HTTPException) as exc:
        app_module.ensure_unique_short_code(db, desired="alias1")
    assert exc.value.status_code == 400


def test_cleanup_expired_and_inactive_links_moves_to_history(app_module, db, now_utc):
    expired = app_module.Link(
        short_code="exp1",
        original_url="https://expired.example",
        expires_at=now_utc - timedelta(minutes=1),
    )
    inactive = app_module.Link(
        short_code="inact1",
        original_url="https://inactive.example",
        last_accessed_at=now_utc - timedelta(days=app_module.INACTIVE_DELETE_DAYS + 1),
    )
    db.add_all([expired, inactive])
    db.commit()

    app_module.cleanup_expired_and_inactive_links(db)

    remaining = db.query(app_module.Link).all()
    assert remaining == []

    hist = db.query(app_module.ExpiredLinkHistory).order_by(app_module.ExpiredLinkHistory.short_code).all()
    assert [h.short_code for h in hist] == ["exp1", "inact1"]
    assert all(isinstance(h.expired_at, datetime) for h in hist)

