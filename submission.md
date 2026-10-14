# Mixtape Bug Hunt — Submission

## AI Usage

I did this project with Claude Code, an AI coding agent running in my terminal with access to the repo. It did much more than answer questions: it read files, ran commands, edited code, and made commits. My role was mostly to give it the project brief and issue reports, steer the pace, and review what it produced. This section describes that split as it actually happened.

**What I asked it to do, and what it did**

- **Orientation:**
  - I gave it the project context. It read `README.md`, `models.py`, every service, route and test, and `seed_data.py`.
  - It set up the virtualenv and ran `pytest` to get a baseline: 4 failing tests, covering issues #1, #3 and #5. Issues #2 and #4 had no tests at all.
  - It drafted the codebase map from that reading.
- **Reproducing each issue:**
  - I pasted each issue report one at a time.
  - For each, the AI wrote a small script that replays the reporter's exact scenario, such as kenji's streak of 12 going from Saturday to Sunday, or nova's feed with a friend who listened at 11pm.
  - It ran each script against the original code to show the bug, then against the fix.
  - For #4 it went through the real HTTP endpoints with Flask's test client.
- **Tracing the cause:** it followed each endpoint from its route to the service function behind it. It used grep to find every place that writes the same data, for example the only code that writes `listening_streak`, and the only caller of `create_notification`.
- **Fixes and tests:** it made the code changes and added regression tests for #2 and #4, which had none. It confirmed each new test fails on the old code and passes on the new.
- **Side-effect checks and write-ups:**
  - It ran a script testing both sides of each boundary (Sunday, midnight UTC), plus related features that touch the same data: the activity feed, re-rating a song, and mark-as-read.
  - It drafted the root cause entries and this section.

**Where the AI was wrong or incomplete, and what caught it**

- **Issue #2, wrong first fix.** The AI's first fix narrowed the "listening now" window from 24 hours to 30 minutes, because a comment in `seed_data.py` called events within 30 minutes "listening now". When I pasted nova's actual report, it says the expected behavior is "only friends who have listened today appear". The AI re-ran its reproduction against the 30-minute version, and it hid a friend who had listened earlier that same day. The real problem was using a rolling window at all, not its length. The final fix uses the start of the current day. Lesson: a code comment isn't the spec, and the user's report should win.
- **Running ahead of the process.** Before I'd shared the individual reports, the AI started fixing several bugs in a row from the code alone. I told it to go one issue at a time, and that's what exposed the #2 mistake above. It also guessed at the five fields for the root-cause write-up before I gave it the real format, and it said it was guessing.
- **An over-general claim in the codebase map.** Its first draft said every route delegates to a service. On re-checking, `GET /users/<id>` queries the database directly, so it corrected the sentence.
- **A bug outside the five issues.** While reproducing #4, its test hit a 500 error when adding a song to a playlist on a fresh database. It flagged this and kept it out of the #4 fix instead of widening the change.
- **Tooling slips.** A scripted edit failed on a file with mixed line endings, and an output filter once hid the result lines it was trying to check. Both times it noticed and re-ran the step, rather than reporting success from incomplete output.

**What I verified myself**

- I ran the tests myself to check that all three fixes (#1, #2 and #4) work, rather than relying on the AI's report that they did.
- I ran `git log --oneline` on the `bugfix/mixtape` branch myself to confirm there is one `fix:` commit per bug.
- I pasted each issue report to the AI one at a time and made it reproduce and document each bug before moving to the next. That pacing is how the wrong first fix for #2 was caught.

## Codebase Map

Mixtape is a Flask + Flask-SQLAlchemy JSON API backed by SQLite. There is no frontend; every feature is an HTTP endpoint that returns JSON. The code is split into three layers: **models** (the data), **routes** (HTTP), and **services** (logic).

### Entry point and configuration

- **`app.py`**: Defines the shared `db = SQLAlchemy()` object and the `create_app(config=None)` factory. The factory sets defaults (`sqlite:///mixtape.db`, overridable through the `DATABASE_URL` env var), merges in any `config` dict, binds `db` to the app, and registers four blueprints under URL prefixes: `/songs`, `/playlists`, `/users`, `/feed`. It also calls `db.create_all()`, so tables exist as soon as an app is created. The tests rely on this by passing `sqlite:///:memory:` to get a fresh database per test.
- **`seed_data.py`**: Drops and recreates the schema, then inserts a fixed scenario. There are 5 users (nova, darius, simone, kenji, aaliya) with bidirectional friendships, 10 tags, 25 songs with 0, 1, or 3+ tags, 3 playlists, listening events spread over the past days, preset streak values, and one `song_added_to_playlist` notification. Join tables (`friendships`, `song_tags`, `playlist_entries`) are populated with raw `table.insert()` statements, not through ORM relationships.

### Data model (`models.py`)

Seven SQLAlchemy models, all keyed by string UUIDs from `generate_uuid()`:

| Model | Purpose | Key columns / relationships |
|---|---|---|
| `User` | An account | `username`, `email` (both unique), `listening_streak`, `last_listened_at`. Has `shared_songs`, `ratings`, `listening_events`, `notifications`, `playlists`, and a self-referential `friends` relationship (lazy `"dynamic"`, so `user.friends` is a query, not a list). |
| `Tag` | A genre-like label | Unique `name`. |
| `Song` | A song a user shared | `title`, `artist`, `album`, `genre`, `shared_by` (FK → User), `shared_at`, `share_note`. `tags` is many-to-many through `song_tags`, loaded with `lazy="subquery"`. |
| `ListeningEvent` | One play of one song by one user | `user_id`, `song_id`, `listened_at`. |
| `Rating` | A 1–5 score | `user_id`, `song_id`, `score`, `rated_at`. A `UniqueConstraint(user_id, song_id)` allows one rating per user per song. |
| `Playlist` | A named, ordered song list | `name`, `created_by`, `is_collaborative`. `songs` is many-to-many through `playlist_entries`. |
| `Notification` | A message to a user | `user_id` (recipient), `notification_type` (short string such as `song_added_to_playlist` or `song_rated`), `body`, `read`. |

Three association tables:

- **`friendships`** `(user_id, friend_id)`: a directed edge. A friendship is symmetric only because the seed inserts both directions.
- **`song_tags`** `(song_id, tag_id)`: a plain many-to-many link.
- **`playlist_entries`** `(playlist_id, song_id, position, added_by, added_at)`: more than a link table. It records an explicit `position` for ordering, plus who added each song and when. `(playlist_id, song_id)` is the primary key, so a song can appear at most once per playlist.

Each model has a `to_dict()` that turns it into JSON. Datetimes become ISO strings, `Song.to_dict()` adds a `tags` list of names, and `User.to_dict()` leaves out `email`.

### Routes (`routes/`): the HTTP layer

| File | Endpoints | Service calls |
|---|---|---|
| `songs.py` | `GET /songs/search?q=`, `GET /songs/<id>`, `POST /songs/<id>/rate`, `POST /songs/<id>/listen` | `search_service`, `notification_service.rate_song`, `streak_service.record_listening_event` |
| `playlists.py` | `POST /playlists/`, `GET /playlists/<id>`, `GET`/`POST /playlists/<id>/songs` | `playlist_service`, `notification_service.add_to_playlist` |
| `users.py` | `GET /users/<id>`, `GET /users/<id>/streak`, `GET /users/<id>/notifications[?unread_only=true]`, `POST /users/notifications/<id>/read` | `streak_service.get_streak`, `notification_service` |
| `feed.py` | `GET /feed/<id>/listening-now`, `GET /feed/<id>/activity` | `feed_service` |

### Services (`services/`): the logic layer

- **`streak_service.py`**: `record_listening_event()` creates a `ListeningEvent` and calls `update_listening_streak()`. That function compares today's UTC date with `user.last_listened_at` and applies the streak rules: first listen, same day, next day, or gap. `get_streak()` reads the stored value.
- **`feed_service.py`**: `get_friends_listening_now()` collects the user's friend IDs, queries their `ListeningEvent`s after a time cutoff, newest first, and keeps one entry per friend (their most recent). `get_activity_feed()` returns the latest N friend events with no time filter.
- **`search_service.py`**: `search_songs()` does a case-insensitive `ilike` match on `Song.title` or `Song.artist`. `get_song()` fetches one song by ID.
- **`notification_service.py`**: The low-level `create_notification()` writes a `Notification` row. Two user actions that notify someone also live here: `add_to_playlist()`, which attaches a song to a playlist and notifies the song's sharer, and `rate_song()`, which creates or updates a `Rating` and notifies the sharer. Reads are `get_notifications()` and `mark_as_read()`.
- **`playlist_service.py`**: `create_playlist()`, `get_playlist()` (metadata only), `get_user_playlists()`, and `get_playlist_songs()`, which joins `Song` to `playlist_entries` and orders by `position`.

### Data flow: a user rates a song

1. The client sends `POST /songs/<song_id>/rate` with JSON `{"user_id": ..., "score": ...}`.
2. **`routes/songs.py:rate()`** reads the body and returns `400` if `user_id` or `score` is missing. It converts `score` to `int` and calls `rate_song(user_id, song_id, score)`.
3. **`services/notification_service.py:rate_song()`**:
   - Raises `ValueError` unless `1 <= score <= 5`.
   - Loads the `Song` and the rating `User` with `db.session.get()`, raising `ValueError` if either is missing.
   - Looks for an existing `Rating` with that `(user_id, song_id)`. If one exists, it updates `score`. Otherwise it adds a new `Rating`. This mirrors the table's unique constraint.
   - Commits the rating.
   - If the rater isn't the song's sharer (`song.shared_by`), calls `create_notification()` with type `song_rated`. That function inserts a `Notification` for the sharer and commits it in its own transaction.
   - Returns the `Rating`.
4. Back in the route, a `ValueError` becomes `400 {"error": ...}`. On success it returns `201` with `rating.to_dict()`.
5. The sharer sees the result later through `GET /users/<id>/notifications` → `routes/users.py:notifications()` → `get_notifications()`, which returns their notifications newest first.

### Data flow: a user listens to a song

`POST /songs/<id>/listen` → `routes/songs.py:listen()` → `streak_service.record_listening_event()`. It writes a `ListeningEvent` with `listened_at = now (UTC)`, then `update_listening_streak()` updates `User.listening_streak` and `last_listened_at` in the same commit. One request writes two places, and two features read them:

- The **streak** endpoint (`GET /users/<id>/streak`) reads the denormalized counter on `User`.
- The **feed** endpoints (`/feed/<id>/listening-now` and `/activity`) query the `ListeningEvent` rows of the user's friends.

### Patterns in how the app is organized

- **Thin routes, fat services.** Routes parse input, call one service function, and format the response. Business rules, queries, and commits all live in `services/`. The one exception is `GET /users/<id>`, which does a direct `db.session.get(User, ...)` because it's a plain lookup. To debug an endpoint, go straight from the route to the service it calls.
- **Errors as `ValueError`.** Services raise `ValueError` for "not found" and invalid input. Each route catches it and maps it to a status code: `404` for lookups, `400` for writes.
- **Services commit their own work.** Each mutating service function calls `db.session.commit()` itself, so a route never manages transactions.
- **Services return plain data.** Read services usually return `to_dict()` results (lists of dicts). Write services return model instances, which the route serializes.
- **Files are grouped by side effect, not by model.** `notification_service.py` owns writes that cause a notification (playlist adds, ratings), so the action and its notification sit side by side. The playlist write path lives in `notification_service`, while playlist reads live in `playlist_service`.
- **Time is UTC throughout.** Models default to `datetime.now(timezone.utc)`. Services compute "today" and time windows from UTC. SQLite stores datetimes without tzinfo, so code that reads them back re-attaches UTC before comparing.
- **Tests build their own world.** Each test file creates an app on an in-memory SQLite database, seeds just the rows it needs (often with raw association-table inserts), and calls service functions directly or goes through `app.test_client()`.

---

## Root Cause Analyses

**Issue #1 — My listening streak keeps resetting**

_Commit `309c856` — `fix: stop resetting listening streak on Sundays`_

**How I reproduced it.**
- I ran `pytest tests/` on the untouched code. `test_streak_increments_on_sunday` failed with `assert 1 == 2`: a Saturday listen followed by a Sunday listen left the streak at 1.
- I then replayed kenji's exact report in a script against the pre-fix `streak_service.py`. I made a user with `listening_streak=12` and `last_listened_at` = Saturday 2024-06-15 22:00 UTC, then called `update_listening_streak()` for Sunday 09:00 and Monday 09:00.
- Output: `Sunday: 1`, `Monday: 2`. That matches the report: the streak dropped to 1 on Sunday and counted up again from Monday.

**How I found the root cause.**
1. kenji checked the streak with `GET /users/<id>/streak`. That route calls `streak_service.get_streak()`, which only returns `user.listening_streak`, so the read path couldn't change the value. The bad value had to be written earlier.
2. The only writer of `listening_streak` (from a grep) is `update_listening_streak()`. It is called from `record_listening_event()`, which `POST /songs/<id>/listen` in `routes/songs.py` uses.
3. That function has four branches. The report gave me the exact inputs: last listen Saturday, now Sunday, so `days_since_last == 1`. That should hit the increment branch, but the streak ended at 1, so execution must have fallen through to `else`.
4. The increment condition is `days_since_last == 1 and today.weekday() != 6`. Python's `date.weekday()` numbers Monday as 0 and Sunday as 6.

I was sure this was the cause, and not just a suspicious line, because it fully explains both details of the report: it only ever happened on Sundays, and Monday counted normally again from 1.

**The root cause.** The function's docstring says a streak increments "if the user listened yesterday", with no mention of weekdays. The code added a second condition, `today.weekday() != 6`. On a Sunday that condition is `False`, so a listen exactly one day after Saturday's skips the `+= 1` branch. It lands in the `else` branch meant for skipped days, which sets `listening_streak = 1`. Any streak running through a Sunday was reset as if the user had missed a day.

**My fix.** I removed the weekday condition, so the branch is `elif days_since_last == 1:`. That's a one-line change. Whether two listens are on consecutive days depends only on the calendar-date difference already computed in `days_since_last`, which now matches the documented rules. The first-listen, same-day, and gap branches are untouched.

**My side-effect check.**
- All 5 tests in `tests/test_streaks.py` pass, including `test_streak_resets_after_skipped_day`, so real resets still happen.
- I tested both sides of the Sunday boundary:

  | Case | Result |
  |---|---|
  | Sat → Sun | increments |
  | Sun → Mon | increments |
  | Fri → Sun (skipped Saturday) | resets to 1 |
  | Sat → Mon (skipped Sunday) | resets to 1 |
  | Sun → next Sun, 7-day gap | resets to 1 |
  | Sun 08:00 → Sun 20:00 | unchanged |
  | Sat 23:59 → Sun 00:01, across the date boundary | increments |

- SQLite returns `last_listened_at` without tzinfo after a reload. The existing `.replace(tzinfo=timezone.utc)` handles that, and a Sat → Sun check after a real database round trip also incremented.
- Nothing else reads `weekday()` or writes `listening_streak` (checked with grep), so no other feature depended on the removed condition.

---

**Issue #2 — Friends Listening Now shows people from yesterday**

_Commit `b870a05` — `fix: only show friends who listened today in Friends Listening Now`_

**How I reproduced it.**
- There was no existing test for the feed, so I built nova's scenario in a script against the original `feed_service.py`:
  - nova has two friends: darius, whose only `ListeningEvent` was at 23:00 UTC the previous day, and kenji, who listened at 00:00 UTC today.
  - I called `get_friends_listening_now(nova.id)`, the function behind `GET /feed/<id>/listening-now`.
- Result: `['kenji', 'darius']`. darius appeared even though he hadn't listened at all today, which is exactly nova's report.

**How I found the root cause.**
1. `routes/feed.py:listening_now()` passes straight through to `feed_service.get_friends_listening_now()`.
2. That function filters `ListeningEvent.listened_at >= cutoff` and then keeps one most-recent entry per friend. The deduplication and ordering only rearrange events that already passed the filter, so a stale event showing up meant the cutoff itself was too permissive.
3. The cutoff was `datetime.now(timezone.utc) - RECENT_THRESHOLD`, with `RECENT_THRESHOLD = timedelta(hours=24)`.
4. The moment I was sure was matching that to nova's wording: stale entries hang around "until the same time the next day". That is the exact behavior of a rolling 24-hour window.

My first fix shrank the window to 30 minutes, based on a comment in `seed_data.py`. When I re-read the report, its stated expectation was "only friends who have listened today appear". I re-ran the repro against the 30-minute version and it returned `[]`: it also hid kenji, who had listened today. So the problem wasn't the window's length. It was that a rolling window is the wrong kind of cutoff. I replaced that attempt before finalizing the commit.

**The root cause.** The feature promises friends who listened today, but `get_friends_listening_now()` measured "recent" as a rolling 24 hours ending now. A rolling window reaches back into the previous calendar day for most of the day. At 09:00 it covers everything since 09:00 yesterday. So darius's 23:00 listen, only 10 hours old, passed `listened_at >= cutoff` and stayed in the feed until 23:00 the next day.

**My fix.** I changed the cutoff to the start of the current calendar day in UTC: `datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)`. I also removed the now-unused `RECENT_THRESHOLD` constant and its `timedelta` import, and updated the docstring. Anything from before midnight is now excluded, and everything from today is included however long ago it was. UTC midnight is the same day boundary `streak_service` uses for streaks, so "today" means the same thing in both features. I added `tests/test_feed.py` with events pinned to midnight UTC, so the tests don't depend on what time they run.

**My side-effect check.**
- The new "excludes yesterday" test fails on the original code and passes after the fix.
- I tested both sides of the midnight boundary with real database rows:

  | Event time | In feed? |
  |---|---|
  | exactly 00:00:00 | included |
  | 00:00:01 | included |
  | 23:59:59 yesterday | excluded |
  | 23:00 yesterday | excluded |
  | 2 days ago | excluded |

  This also confirmed that comparing the timezone-aware cutoff against SQLite's naive stored datetimes works correctly.
- A friend with both a yesterday event and a today event appears once, with today's song, so deduplication still works.
- A user with no friends still gets `[]`.
- `get_activity_feed()` (`/feed/<id>/activity`) shares the file and the friend lookup but intentionally has no time filter. I confirmed it still returns all six friends' events, including the old ones.

  **Known limitation:** "today" is the UTC day, because the app stores no per-user timezone. A user far from UTC sees the feed roll over at a local time other than midnight. The streak service has the same limitation.

---

**Issue #4 — I got notified when a friend added my song to a playlist but not when they rated it**

_Commit `89fe154` — `fix: notify song sharer when a friend rates their song`_

**How I reproduced it.**
- I followed aaliya's steps through the real HTTP routes with Flask's `test_client()` on a fresh in-memory database. aaliya shared two songs, and kenji called `POST /songs/<song2>/rate` with `{"score": 5}`.
- The response was `201` with `score: 5`, so the rating was saved. `GET /users/<aaliya>/notifications` then returned no notifications.
- The add-to-playlist half of the report is the working comparison case. The seed data's existing `song_added_to_playlist` notification shows what that path produces.

**How I found the root cause.**
1. `routes/songs.py:rate()` only validates the body and calls `notification_service.rate_song()`. It doesn't create notifications itself and doesn't swallow errors, so the missing notification had to come from the service.
2. The working path, `POST /playlists/<id>/songs`, leads to `add_to_playlist()` in the same file. I read the two functions side by side. Both look up the song and the acting user, write their row, and commit. `add_to_playlist()` then ends with `if song.shared_by != added_by_user_id: create_notification(...)`. `rate_song()` ends with `db.session.commit()` and `return rating`.
3. A grep for `create_notification` showed exactly one caller, `add_to_playlist`. Meanwhile `create_notification`'s own docstring names `'song_rated'` as a notification type.

That confirmed it. Nothing in the codebase ever creates a `song_rated` notification, so there was no condition that could fail. The step simply isn't there.

**The root cause.** `rate_song()` in `services/notification_service.py` never calls `create_notification()`. The rating is validated and saved correctly, which is why it "shows on the song". But the function returns before notifying anyone, unlike its sibling `add_to_playlist()`. No error is raised and the route returns `201`, so the failure is silent. That matches aaliya's "no delay, just nothing", and it happens for every user, as she reported.

**My fix.** After the rating is committed, `rate_song()` now creates a notification for the song's sharer. It uses the same guard as `add_to_playlist()`, `if song.shared_by != user_id`, so rating your own song doesn't notify you. The notification has type `song_rated` and a body like `"kenji rated your song 'Golden Hour' 5/5."`. It runs after the rating commit, so a notification is only created for a rating that was actually saved. I added `tests/test_notifications.py`, which goes through the real `/rate` and `/notifications` endpoints.

**My side-effect check.**
- The "notifies sharer" test fails on the original code and passes after the fix. The "self-rating doesn't notify" test passes in both, which confirms the guard.
- Re-rating the same song still updates the single existing `Rating` row (count stays 1, score becomes the latest), so the `UniqueConstraint(user_id, song_id)` path is unaffected. Each rating event produces its own notification.
- An invalid score (6) still raises `ValueError` before any write, and no notification is created.
- The rater receives no notifications.
- `song_added_to_playlist` notifications are still created alongside `song_rated` ones.
- `mark_as_read()` and the `unread_only=true` filter work across both types.
- **Found while checking:** on a fresh database, `POST /playlists/<id>/songs` itself returns a 500 (`NOT NULL constraint failed: playlist_entries.position`). `add_to_playlist()` uses `playlist.songs.append(song)`, and that can't supply the required `position` and `added_by` columns. This happens before and after my change and lives in a different function, so I left it out of scope for this fix rather than widen the change.
