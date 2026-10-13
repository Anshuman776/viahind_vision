# VIAHIND Vision — PG Surveillance System

Entrance monitoring for PG (paying guest) accommodation. VIAHIND Vision watches authorised entrance
cameras, detects and tracks people, records **entry** and **exit** events when a tracked person crosses
a configured entrance line, keeps an event snapshot for each crossing, and maintains a searchable log,
visits and an occupancy count.

- **Overview**: people currently inside, entries, exits and unknown visitors today, a live preview, camera connection, an hourly chart and recent activity.
- **Live Camera**: start, stop and reconnect cameras, see what the server receives (with tracking overlay), and draw the entrance line and its direction.
- **Entry & Exit Logs**: filter, search, review, correct, link visits, view snapshots, export CSV.
- **Settings**: site, timezone, detection and tracking, retention, cameras, operator accounts, integrations.

All figures come from persisted records. Nothing on screen is simulated, except in the separate demo mode, which uses its own database and shows a banner.

---

## 1. Architecture

```
browser (Next.js 16, React 19)                       backend (FastAPI)
 ├─ /overview /live /logs /settings                   ├─ routers/        REST API (/api/v1)
 ├─ /streamer (phone as camera)          /api/v1 ──►  ├─ auth.py         bcrypt + JWT in httpOnly cookie, roles, CSRF header
 │    same-origin rewrite (next.config.ts)            ├─ services/       events, visits, occupancy, stats, retention, audit
 └─ WebSockets ───────────────────────── :8000 ──►   ├─ vision/
      /ws/alerts  status + new events                 │   ├─ camera_manager.py  one worker per camera
      /ws/live/{id}  live frames + overlay            │   ├─ camera_worker.py   capture → detect/track → line crossing → events
      /ws/stream/{id}  browser camera frames in       │   ├─ line_crossing.py   entry/exit/uncertain logic (pure, unit-tested)
                                                      │   ├─ detector.py        YOLO + ByteTrack (from viahind-person-counter)
                                                      │   ├─ anomaly.py         boundary to the existing anomaly model
                                                      │   └─ sources.py         camera source validation / encryption / masking
                                                      ├─ edge-agent/     rtsp_reader.py (OpenCV reader), fight_detector.py (existing)
                                                      ├─ models/entities.py + migrations/   SQLAlchemy + Alembic
                                                      └─ storage/        SQLite DB, event snapshots, test clips (git-ignored)
```

**Camera types**

| Type | How frames arrive | Typical use |
|---|---|---|
| Browser camera | A signed-in operator's browser sends JPEG frames over an authenticated WebSocket | Laptop/USB webcam, or a phone using `/streamer` |
| IP / CCTV | Backend worker opens an `rtsp://`, `rtsps://`, `http(s)://` (MJPEG) URL with OpenCV | IP cameras, DVR/NVR RTSP outputs |
| USB camera on server | Backend opens device index `0`, `1`, … | Webcam plugged into the server |
| Test clip | Backend plays a file from `backend/storage/test_videos/` at native speed | Development and testing only |

A camera shows **Live** only while the backend is actually receiving frames (no frame for
`CAMERA_STALE_SECONDS`, 5 s by default, means Disconnected).

---

## 2. Install and run

Requirements: Python 3.11+ and Node.js 20+.

### Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate            # Windows   (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env            # Linux/macOS: cp .env.example .env
```

Edit `backend/.env`:

- `SECRET_KEY`: generate one with `python -c "import secrets; print(secrets.token_hex(32))"`.
- `PERSON_MODEL_PATH`: path to an existing YOLO checkpoint, for example the `yolo11n.pt` from `viahind-person-counter`. Weights are **never downloaded automatically**. Without it, cameras still stream but no entries or exits are recorded, and the UI says so.

Then:

```bash
python manage.py create-user admin --role admin     # prompts for a password; also applies migrations
uvicorn main:app --host 0.0.0.0 --port 8000
```

Migrations also run automatically at startup (`alembic upgrade head`). Health: `GET /health` (liveness), `GET /health/ready` (database, storage, detector, anomaly, pending writes).

### Frontend

```bash
cd frontend
npm install --legacy-peer-deps
npm run dev        # http://localhost:3000
```

For production: `npm run build && npm start`. Set `BACKEND_URL` before building if the API is not on `127.0.0.1:8000` (see `frontend/.env.example`).

### Demo mode (synthetic records)

```bash
cd backend
set APP_ENV=demo                  # Linux/macOS: export APP_ENV=demo
python manage.py seed-demo        # writes only to DEMO_DATABASE_URL
uvicorn main:app --port 8000
```

The UI shows a "Demo mode" banner. Demo records have no photos, and `seed-demo` refuses to run outside `APP_ENV=demo`.

---

## 3. Connecting cameras

Add cameras in **Settings → Cameras** (administrators only), then use **Live Camera**.

**Laptop or USB webcam (browser camera)**
1. Add a camera of type *Browser camera*.
2. Open **Live Camera**, select it and press **Start Camera**. The browser asks for camera permission at this point and not before.
3. Capture continues while you move between pages. *Stop Camera* releases the webcam.

**Phone at the entrance (browser camera)**
1. Add a *Browser camera* and open `/streamer` on the phone (the Live Camera page links to it), sign in and press **Start**.
2. Phones only allow camera access on **HTTPS** pages (`http://localhost` is the only exception). Serve the frontend over HTTPS on your LAN, for example behind a reverse proxy with a certificate, or with `npx next dev --experimental-https` for testing.
3. In development, add the PC's LAN IP to `NEXT_DEV_ALLOWED_ORIGINS` and allow ports 3000/8000 in the firewall.

**CCTV / DVR / IP camera (RTSP or HTTP)**
1. Find the RTSP URL in the camera or DVR manual (e.g. `rtsp://user:pass@192.168.1.20:554/Streaming/Channels/101`).
2. Prefer keeping credentials out of the database: put `CAMERA_GATE_URL=rtsp://…` in `backend/.env` and enter `env:CAMERA_GATE_URL` as the source.
3. Otherwise the URL is stored **encrypted** (key derived from `SECRET_KEY`). It is never returned by the API, never sent to the browser and never logged. The UI shows only `rtsp://***@host:port/path`.
4. The backend must be able to reach the camera. Do not expose camera streams to the internet.

**Test clip**: put an `.mp4` in `backend/storage/test_videos/` and add a *Test clip* camera with the file name. Clips start playing once the detector has loaded.

---

## 4. Entry/exit logic

1. Each frame goes to YOLO (person class only) with ByteTrack tracking. Track IDs are per camera session.
2. The operator draws the **entrance line** on the live image, and the arrow points **inside**.
3. A track must be confirmed on one side (outside the tolerance band, for `min_side_frames` frames), then confirmed on the other side, *and* its path must pass through the drawn segment:
   - outside → inside = **Entry**, inside → outside = **Exit**.
   - A person merely appearing in the frame never creates an event, and jitter around the line is ignored.
4. **Uncertain** events (shown for review, never counted):
   - a track lost while half-way across the line (occlusion, leaving the frame),
   - a direction reversal within the cooldown after an event.
5. Duplicate suppression: one event per crossing per track, cooldown per track, and a second track on the same person crossing at the same moment is dropped.
6. Tracks expire after `track_timeout_seconds`. When a camera disconnects, all tracks are dropped, a new session begins, and an interruption is logged.

**Labels and visits.** The first event of a track gets the next site-wide pseudonymous label (`Unknown Person 01`, `02`, …). An entry opens a visit. An exit closes a visit **only** if the same track made the entry (tracker continuity). Any other exit is *Unmatched*: it still counts toward occupancy, but no visit is closed and no duration is shown until an operator links it. Events are never paired by time proximity. There is no facial recognition or biometric matching.

**Occupancy** = last head count (reconciliation) + entries − exits ± manual adjustments since then, applied in time order and never below zero. Uncertain and rejected events don't count. The value is shown as **Estimated**, with reasons, after camera interruptions, service restarts, an exit at zero (a missed entry) or unreviewed uncertain events. Operators clear it with **Reconcile** on the Overview page. Reconciliations and adjustments are audited.

### Testing entry and exit
- **Live**: start a camera, draw the line across the doorway, walk through toward the arrow, then back. Check **Entry & Exit Logs**.
- **Recorded**: use a *Test clip* camera with any doorway footage you are authorised to use.
- **Automated**: see section 7. The tests use synthetic trajectories and frames, never real residents' footage.

---

## 5. Existing anomaly-detection model

The anomaly component in this repository is `backend/edge-agent/fight_detector.py` (`FightDetector.predict_clip`). It was not modified, retrained or duplicated.

- **Connection point:** `backend/vision/anomaly.py` (`AnomalyDetectorAdapter`), which provides `initialize_anomaly_detector()`, `process_frame()`, `get_anomaly_events()` and `health_check()`.
- It loads `FightDetector` from `edge-agent/`, receives sampled frames from every camera worker, builds clips (`ANOMALY_CLIP_LENGTH`), and runs inference in its **own thread with a bounded queue**. Clips are dropped, never queued, when inference is slow, so the camera feed and entry/exit tracking are never blocked.
- Only outputs where the model reports `is_fight: true` above `FIGHT_CONFIDENCE_THRESHOLD` are stored (`anomaly_events` table, `GET /api/v1/anomaly/events`). Malformed outputs and inference errors produce an error status, not alerts.
- **Current status:** `FightDetector.predict_clip` is a signature placeholder that always returns `is_fight: False`, and no model weights exist in the repository. The adapter therefore reports *"Model not connected"* when enabled. To connect the real model, load the weights in `FightDetector.__init__` (as `self.model`) and implement `predict_clip` with the same output format. Then set `ANOMALY_DETECTION_ENABLED=True`.
- The previous phone-streamer button that broadcast a fabricated "Physical Altercation 94.2%" alert has been removed.

---

## 6. Security and privacy

- **Accounts**: administrators manage settings, cameras and accounts; operators monitor, review and reconcile. Every API route checks the role on the server.
- **Sessions**: a signed JWT in an `httpOnly`, `SameSite=Lax` cookie (`Secure` when `COOKIE_SECURE=True`, which is required in production). State-changing requests also need an `X-VV-CSRF` header. Repeated failed sign-ins are throttled.
- **WebSockets** require a valid session and a same-site `Origin`.
- **Snapshots** are served only to signed-in users through `/api/v1/events/{id}/snapshot`, with `no-store` caching and path-traversal protection. Only event crops are stored, never continuous video.
- **Camera credentials** are encrypted at rest or kept in environment variables, and are masked in all responses and logs.
- **Audit log** covers event corrections, visit links, occupancy changes, camera and settings changes, user changes, sign-ins and CSV exports.
- **Retention**: snapshots are deleted after `snapshot_retention_days` (default 30). Event records can also expire (`event_retention_days`). The job runs hourly.
- **Production** refuses to start with a weak `SECRET_KEY` or without `COOKIE_SECURE`. Serve over **HTTPS** behind a reverse proxy, and never expose ports 8000 or camera streams publicly.

**Your obligations.** Use VIAHIND Vision only on cameras you are authorised to operate. Inform residents and visitors with clear signage that the entrance is monitored and why. Limit access to people who need it. Keep retention as short as practical. Follow the data-protection law that applies to you (in India, the Digital Personal Data Protection Act, 2023). Person labels are pseudonymous; operators should add identifying notes only when there is a legitimate need.

---

## 7. Tests

```bash
cd backend
python -m pytest tests -q
# optional end-to-end check with the real detector (no real footage needed):
VV_TEST_MODEL_PATH=/path/to/yolo11n.pt python -m pytest tests/test_yolo_integration.py

cd frontend
npm test
npx tsc --noEmit
npm run build
```

The backend tests cover entry/exit direction, hysteresis, duplicate suppression, track expiry, uncertain events, occupancy (including missed entries and reconciliation), visit matching and manual linking, corrections and rejections, database-failure retries, low storage, snapshot access control and path traversal, authorization and CSRF, WebSocket auth, camera disconnection and reconnection, unreachable sources, worker crashes, detector failures and the anomaly adapter (including the real `FightDetector` placeholder).

---

## 8. Known limitations

- Re-identification across visits is intentionally not attempted. Most exits are *Unmatched* unless the same track is followed through the entry and exit, so visit durations exist only for reliably linked visits.
- One backend process runs the camera workers. Running several API workers (e.g. `uvicorn --workers 4`) would start duplicate camera workers. Run one backend process per site, or split workers into a separate service.
- CPU inference with `yolo11n` handles roughly 5–10 frames/s per camera. Use a GPU (`DETECTION_DEVICE=cuda:0`) for several cameras.
- Multiple entrances: each camera counts its own line. Overlapping cameras looking at the same door would double-count; configure only one counting camera per doorway.
- `docker-compose.yml` references Dockerfiles that do not exist yet.
