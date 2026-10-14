"""
tests/test_notifications.py — Mixtape

Tests for notifications created when friends interact with a user's songs.
"""

import pytest
from app import create_app, db
from models import User, Song


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture
def seed_users(app):
    """A sharer with one song, and a friend who will rate it."""
    with app.app_context():
        sharer = User(username="aaliya", email="aaliya@example.com")
        friend = User(username="kenji", email="kenji@example.com")
        db.session.add_all([sharer, friend])
        db.session.flush()

        song = Song(title="Golden Hour", artist="Solange K", shared_by=sharer.id)
        db.session.add(song)
        db.session.commit()
        yield {"sharer_id": sharer.id, "friend_id": friend.id, "song_id": song.id}


def get_notifications(client, user_id):
    return client.get(f"/users/{user_id}/notifications").get_json()["notifications"]


def test_rating_notifies_song_sharer(app, seed_users):
    """When a friend rates a song, the person who shared it gets a notification."""
    client = app.test_client()
    resp = client.post(
        f"/songs/{seed_users['song_id']}/rate",
        json={"user_id": seed_users["friend_id"], "score": 5},
    )
    assert resp.status_code == 201

    notifications = get_notifications(client, seed_users["sharer_id"])
    assert len(notifications) == 1
    assert notifications[0]["type"] == "song_rated"
    assert "kenji" in notifications[0]["body"]
    assert "Golden Hour" in notifications[0]["body"]


def test_rating_own_song_does_not_notify(app, seed_users):
    """Rating your own song should not notify yourself."""
    client = app.test_client()
    client.post(
        f"/songs/{seed_users['song_id']}/rate",
        json={"user_id": seed_users["sharer_id"], "score": 4},
    )
    assert get_notifications(client, seed_users["sharer_id"]) == []
