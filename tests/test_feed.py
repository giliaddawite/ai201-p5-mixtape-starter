"""
tests/test_feed.py — Mixtape

Tests for the Friends Listening Now feed.
"""

import pytest
from datetime import datetime, timedelta, timezone
from app import create_app, db
from models import User, Song, ListeningEvent, friendships
from services.feed_service import get_friends_listening_now


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture
def seed_feed(app):
    """A user with two friends: one who listened today, one who listened late last night."""
    with app.app_context():
        me = User(username="me", email="me@example.com")
        active = User(username="active", email="active@example.com")
        stale = User(username="stale", email="stale@example.com")
        db.session.add_all([me, active, stale])
        db.session.flush()

        for friend in (active, stale):
            db.session.execute(friendships.insert().values(user_id=me.id, friend_id=friend.id))

        song = Song(title="Now Playing", artist="Someone", shared_by=me.id)
        db.session.add(song)
        db.session.flush()

        # Anchor to midnight UTC so the test doesn't depend on what time it runs.
        midnight = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        db.session.add_all([
            ListeningEvent(user_id=active.id, song_id=song.id, listened_at=midnight),
            ListeningEvent(user_id=stale.id, song_id=song.id, listened_at=midnight - timedelta(hours=1)),
        ])
        db.session.commit()
        yield {"me": me, "active": active, "stale": stale}


def test_listening_now_includes_recent_friend(app, seed_feed):
    with app.app_context():
        feed = get_friends_listening_now(seed_feed["me"].id)
        usernames = [entry["friend"]["username"] for entry in feed]
        assert "active" in usernames


def test_listening_now_excludes_friend_from_yesterday(app, seed_feed):
    with app.app_context():
        feed = get_friends_listening_now(seed_feed["me"].id)
        usernames = [entry["friend"]["username"] for entry in feed]
        assert "stale" not in usernames
