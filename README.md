# VIAHIND Vision — AI CCTV Business Intelligence

VIAHIND Vision turns existing CCTV cameras (RTSP/HTTP IP cameras, DVR/NVR outputs, USB webcams and
phones) into business figures for shops, supermarkets, restaurants, hotels, offices and other premises:

- **Footfall and occupancy**: entries and exits counted at a configurable line, estimated occupancy per location, reconciliation tools.
- **Reviewable alerts**: explainable rules (restricted zones, dwell time, after-hours activity, unusual traffic, occupancy, camera offline/obstructed, processing problems) and an optional Isolation Forest baseline for unusual activity patterns. Every alert has a reason, the measured values, a severity and a review status.
- **Event evidence**: one snapshot per recorded event or zone alert (never continuous video), with retention, storage limits, access control and audited deletion.
- **Reports**: daily/weekly/monthly footfall, peak hours, weekday pattern, camera and location comparisons, previous-period comparison, alert summaries, CSV export, print/PDF and scheduled email/webhook reports.
- **SaaS foundations**: organizations (tenants), multiple locations, roles (admin / operator / viewer), audit log, plan limits, optional edge → cloud synchronisation.

Everything on screen comes from stored records. Nothing is simulated, except in the separate demo mode, which uses its own database and shows a banner.

> **What it does not do.** Person detection is not identification. Labels such as *Unknown Person 07* are temporary tracking labels; they reset when a camera reconnects and never establish who someone is. There is no face recognition (see §9). Alerts describe measured conditions for human review and are never proof of wrongdoing.

---

## 1. Architecture

```
browser (Next.js 16, React 19, TypeScript)                backend (FastAPI, Python 3.11+)
 ├─ /overview /live /alerts /logs /evidence /reports      ├─ routers/       REST API (/api/v1), every query tenant-scoped
 │  /settings /streamer                                    ├─ auth.py        bcrypt + JWT in httpOnly cookie, roles, CSRF header
 │    same-origin rewrite (next.config.ts) ── /api/v1 ──►  ├─ services/
 └─ WebSockets ─────────────────────────────── :8000 ──►  │   ├─ events, visits, occupancy, stats      counting, per-location occupancy, reports
      /ws/alerts       events, camera status, alerts       │   ├─ alert_rules, alert_engine, alerts     rule catalogue, evaluation, dedup, review
      /ws/live/{id}    live frames + overlay               │   ├─ notifications, report_schedules       email/webhook delivery, retries, rate limits
      /ws/stream/{id}  browser camera frames in            │   ├─ ml_anomaly                            Isolation Forest training / inference
                                                           │   ├─ sync                                  edge outbox, cloud ingest
                                                           │   └─ tenancy, retention, audit, snapshots, evidence
                                                           ├─ vision/
                                                           │   ├─ camera_manager.py / camera_worker.py  capture → detect/track → line + zones → events
                                                           │   ├─ line_crossing.py   entry/exit/uncertain logic (pure, unit-tested)
                                                           │   ├─ zones.py           zone presence / dwell (pure, unit-tested)
                                                           │   ├─ quality.py         brightness / contrast / sharpness probe
                                                           │   ├─ detector.py        YOLO + ByteTrack
                                                           │   └─ sources.py         source validation, SSRF policy, encryption, masking
                                                           ├─ models/entities.py + migrations/   SQLAlchemy 2 + Alembic (SQLite or PostgreSQL)
                                                           └─ storage/       evidence images, model artifacts (git-ignored)
```

**Deployment modes** (`DEPLOYMENT_MODE`)

| Mode | Use |
|---|---|
| `standalone` (default) | One server at the premises (or one per site) runs cameras, API and dashboards. |
| `edge` | Same as standalone, plus every event and correction is queued in a local outbox and pushed to a cloud instance. Recording continues offline; the outbox resumes with backoff and never duplicates events. |
| `cloud` | Accepts pushes from registered edge nodes (`POST /api/v1/sync/events`) for central dashboards and reports. Images and camera credentials never leave the edge. |

One backend process runs the camera workers: run it with **one** uvicorn worker (`--workers 1`), one process per site.

---

## 2. Install and run

Requirements: Python 3.11+ and Node.js 20+ (or Docker).

### Docker (PostgreSQL)

```bash
cp backend/.env.example backend/.env        # set SECRET_KEY, APP_ENV=production, COOKIE_SECURE=True, DEBUG=False
export POSTGRES_PASSWORD='<strong password>'
docker compose up -d --build
docker compose exec backend python manage.py create-user admin --role admin
```

Ports are bound to `127.0.0.1`; put an HTTPS reverse proxy (Caddy, nginx, Traefik) in front. To enable detection, mount YOLO weights read-only (see the commented volume in `docker-compose.yml`) and set `PERSON_MODEL_PATH`.

### Manual

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate                      # Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt         # requirements.txt for production
copy .env.example .env                      # Linux/macOS: cp .env.example .env
python manage.py create-user admin --role admin     # prompts for a password; applies migrations
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
```

```bash
cd frontend
npm install --legacy-peer-deps
npm run dev                                  # http://localhost:3000
# production: npm run build && npm start   (set BACKEND_URL before building if the API is not on 127.0.0.1:8000)
```

Health: `GET /health` (liveness) and `GET /health/ready` (database, storage, detector, pending writes). Migrations also run at startup.

**Key settings** (`backend/.env`, all documented in `.env.example`): `SECRET_KEY`, `APP_ENV`, `COOKIE_SECURE`, `DATABASE_URL`, `PERSON_MODEL_PATH`, `CAMERA_ALLOWED_NETWORKS`, `MAX_SIMULTANEOUS_STREAMS`, `SMTP_*`, `PUBLIC_BASE_URL`, `ML_*`, `DEPLOYMENT_MODE`, `SYNC_*`, `RATE_LIMIT_PER_MINUTE`. Production refuses to start with a weak `SECRET_KEY`, without `COOKIE_SECURE`, or with `DEBUG=True`.

### Organizations, users and demo data

```bash
python manage.py list-orgs
python manage.py create-org acme-retail "Acme Retail" --timezone Asia/Kolkata --plan standard --max-cameras 8
python manage.py create-user priya --role admin --org acme-retail
```

A fresh install has one organization (`default`) with one location. Administrators add locations, cameras and users in **Settings**.

Demo mode (synthetic, separate database, banner shown, never used for ML training):

```bash
set APP_ENV=demo && python manage.py seed-demo --days 14 && uvicorn main:app --port 8000
```

---

## 3. Roles

| Role | Can |
|---|---|
| **Viewer** | Overview, Reports (aggregate figures). No live video, images, logs or alert review. |
| **Operator** | Everything a viewer can, plus live cameras, entry/exit logs, evidence, alert review, occupancy reconciliation. |
| **Administrator** | Everything, plus settings, locations, cameras, zones, alert rules, notifications, schedules, the ML model, users, evidence deletion and the audit log. |

Every API route checks the role on the server, and every record is scoped to the user's organization: another tenant's records answer **404**, exactly like missing ones. WebSocket messages are delivered only to the same organization.

---

## 4. Cameras

Add cameras in **Settings → Cameras**, pick their location, then use **Live Cameras**.

| Type | How frames arrive |
|---|---|
| Browser camera | A signed-in operator's browser (laptop webcam or a phone via `/streamer`, HTTPS required on phones). |
| IP / CCTV | The backend opens `rtsp://`, `rtsps://` or `http(s)://` (MJPEG) with OpenCV/FFmpeg. |
| USB on server | Device index `0`, `1`, … |
| Test clip | A file in `backend/storage/test_videos/` (development; `ALLOW_FILE_SOURCES`). |

- **Test connection** (camera dialog) checks DNS, TCP reachability and that a frame arrives, and explains common failures (wrong port, stream path, credentials, unsupported codec).
- **Credentials**: prefer `env:CAMERA_GATE_URL` (URL kept in the server environment). Otherwise the URL is stored encrypted; it is never returned by the API, sent to the browser or logged; the UI shows `rtsp://***@host:port/path`.
- **Network policy (SSRF protection)**: camera URLs must resolve inside `CAMERA_ALLOWED_NETWORKS` (private LAN ranges by default). Loopback, link-local (including cloud metadata `169.254.169.254`), multicast and reserved addresses are always refused. The check runs on save and again every time a worker opens the stream.
- **Reliability**: capture reconnects with bounded exponential backoff (2 s → 30 s); a camera is *Live* only while frames arrive; outages are recorded as incidents, flag occupancy as estimated and raise a *Camera stream interrupted* alert after a grace period; the last error is kept for diagnostics. `MAX_SIMULTANEOUS_STREAMS` caps concurrent cameras per server.
- **Zones**: administrators draw polygons on the live image. *Restricted* zones alert on any confirmed presence; *dwell* zones alert when someone stays longer than a threshold.
- **Counting**: turn counting off for zone-only cameras. Use one counting camera per doorway.

---

## 5. Counting logic

1. Each frame goes to YOLO (person class) with ByteTrack. Track IDs are temporary and per camera session.
2. The counting line is drawn on the live image; the arrow points inside.
3. A track must be confirmed on one side (outside a tolerance band, for `min_side_frames` frames), then on the other side, and its path must pass through the drawn segment: outside → inside = **entry**, inside → outside = **exit**. Appearing in view never creates an event.
4. **Uncertain** events (reviewed, never counted): a track lost mid-crossing, or a direction reversal within the cooldown.
5. Duplicate suppression: one event per crossing per track, per-track cooldown, and a second track on the same person at the same moment is dropped. Close groups are counted per track; heavily overlapping people can merge into one track (see limitations).
6. Tracks expire after `track_timeout_seconds`; a disconnection drops all tracks, starts a new session and logs an incident.

**Detection vs tracking vs identity.** A *detection* is one box in one frame. A *tracked person* is a sequence of detections the tracker links within one camera session. A *label* (`Unknown Person 07`) is assigned to a track when it first produces an event and is unique within the organization. None of these is an identity: the label is lost when the track ends.

**Visits** pair an entry and exit only when the same track made both (or an operator links them). **Occupancy** per location = last head count + entries − exits ± adjustments since then, never below zero, flagged *estimated* with reasons after interruptions, restarts, exits at zero or unreviewed uncertain events. Operators reconcile from the Overview page; every change is audited.

---

## 6. Alerts

Rules (Settings → Alert rules; enable/disable, severity, parameters, re-notification cooldown):

| Rule | Triggered when |
|---|---|
| Restricted zone entry | a tracked person is confirmed inside a restricted zone (snapshot attached) |
| Long presence in a zone | continuous presence exceeds the zone's dwell threshold (snapshot attached) |
| Activity outside business hours | an entry/exit occurs outside the location's hours (with grace) |
| Unusual entry/exit frequency | entries + exits on a camera exceed a threshold within a window |
| Unexpected occupancy | estimated occupancy exceeds capacity, or changes by more than N within a window |
| Repeated line crossings | one track crosses the line N times within a window |
| Camera stream interrupted | a monitoring camera delivers no video beyond a grace period (auto-resolves) |
| Camera view obstructed/degraded | sustained very dark, uniform (covered) or blurred image (auto-resolves) |
| Processing or delivery problem | detection failing, events waiting for the database, or cloud sync delayed (auto-resolves) |
| Unusual activity pattern | the Isolation Forest baseline scores an hour as an outlier (§7) |
| Video anomaly | the trained altercation classifier, or the motion detector, confirms a detection over consecutive clips (§8) |

**Deduplication**: while an alert with the same subject is open, new occurrences update it (count, last seen, latest metrics) instead of creating duplicates. Notifications are re-sent only after the rule's cooldown or when severity increases. **Review**: *new → acknowledged → resolved / dismissed* (dismissed = false positive), with notes, reviewer and audit history; closed alerts can be reopened.

**Notifications** (Settings → Notifications): in-app is always on (real-time badge and Alerts page). Telegram (bot messages, optionally with the evidence photo), email (SMTP, optionally with the photo attached) and webhooks per organization; a single-business install can also set `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` / `ALERT_EMAIL_TO` in `.env`. Each channel has a minimum severity, optional categories, an hourly rate limit (excess = *suppressed*), retries with backoff (5 attempts) and a delivery log. Webhooks are signed: `X-VV-Signature: sha256=<HMAC-SHA256 of the body with the channel secret>`. Bot tokens, channel secrets and recipients are encrypted at rest and never returned. Images go out only on channels where an administrator ticked *Attach the evidence snapshot*; webhooks never carry images.

**Mail server** (Settings → Mail server): the SMTP account that sends emails (Gmail / Outlook / Zoho presets, STARTTLS or SSL/TLS, *Send test*). It is stored encrypted per organization and the password is never returned. Without it, the `SMTP_*` values in `.env` are used.

### Guard Room: camera guards and the head guard

Every camera is a **guard** at a **post** (main gate, entrance, corridor, common room, restricted area, perimeter, general) with **duties**:

| Duty | Alert rules it reports | Needs on the camera |
|---|---|---|
| Gate entry / exit log | repeated crossings | counting line |
| Curfew / after-hours watch | after hours | counting line + location hours |
| Crowding & headcount | traffic frequency, occupancy | counting line |
| Fight / altercation watch | video anomaly model (the model only analyses cameras with this duty) | video anomaly detector |
| Restricted area watch | restricted zone | a restricted zone |
| Loitering watch | zone dwell | a monitored zone |

A guard only reports its own duties. Camera offline, obstructed view and processing problems are always reported. A camera without a post keeps every duty, so existing setups behave as before.

The **head guard** (`services/head_guard.py`) receives every report and:
- groups reports at one location within *N* minutes (default 10) into one **incident**, and raises the severity one level when a second guard reports it;
- writes what the guards saw and **what to do next** (playbooks per report type: fight, restricted area, curfew, camera offline…);
- sends the owner **one message per incident** (when it starts, gets worse or another guard confirms it), not one per alert, through the notification channels. The evidence photo is attached when the channel allows it;
- closes quiet incidents automatically once all their reports are closed, and can send a **daily briefing** (gate log, incidents, reports per guard) at a chosen hour;
- keeps a **what to do next** list: cameras that cannot see or are off duty, missing counting lines and zones, curfew hours not set, no owner channel, no mail server.

One server runs up to `MAX_SIMULTANEOUS_STREAMS` cameras (default 16). Turn the head guard off in the Guard Room to go back to one notification per alert.

---

## 7. Unusual-pattern detection (Isolation Forest)

A staged approach: rules first; then this optional statistical baseline; advanced temporal/video models only once enough representative data exists.

- **Features (schema v1)**, one row per location per local hour: entries, exits, uncertain crossings, net flow, and cyclic hour-of-day / weekday encodings. Counts are standardised with the training mean/std stored with the model.
- **Training** (Settings → Unusual patterns, or `python manage.py train-anomaly-model --org <slug>`) uses only real, non-demo, non-rejected events, and excludes hours overlapping a camera outage. It requires `ML_MIN_TRAINING_HOURS` (168) usable hours over `ML_MIN_TRAINING_DAYS` (7) days and 50 events; otherwise the run is recorded as *insufficient data* and no model is produced.
- **Artifacts** are versioned in `MODEL_DIR/org_<id>/`, registered with their SHA-256, loaded only from inside `MODEL_DIR` and only if the hash matches (a tampered file disables the model). Only the last 3 artifacts are kept. joblib files are pickles: never copy model files from untrusted sources.
- **Inference** runs hourly, separately from training; rows with missing/invalid features are skipped. Findings become **low**-severity alerts that explain the hour (e.g. "80 entries between 03:00 and 04:00, compared with about 0.4 in that hour in the training data") with the score and threshold.
- **Evaluation**: the status page shows training-set flag rate and reviewer feedback (resolved vs dismissed) as a running false-positive estimate. Tune `contamination` when retraining.

---

## 8. Video anomaly detection (VIAHIND-FightClassifier-MobileNetV3)

Enabled by default (`ANOMALY_DETECTION_ENABLED=True`). Each camera's frames are sampled into 16-frame clips and analysed in a separate thread with a bounded queue, so counting is never slowed down. A detection must repeat for `ANOMALY_MIN_CONSECUTIVE_CLIPS` (2) clips in a row before it becomes a **high**-severity *Video anomaly* alert with a snapshot. `VIDEO_ANOMALY_MODE` chooses the detector:

| Mode | What it does |
|---|---|
| `auto` (default) | Uses the trained classifier when `FIGHT_MODEL_PATH` is set, otherwise the motion detector. |
| `model` | Trained classifier only. Startup reports an error without weights. |
| `motion` | Weight-free detector: **vigorous movement between people in close contact**, measured with optical flow in the area around tracked people and compared with motion elsewhere in the frame (ignores camera shake). It needs person detection, does not recognise fights, and can be triggered by hugging, play or crowding. |

**Training the classifier** (MobileNetV3-Small per frame + feature differences + GRU, `backend/vision/fight_model.py`):

```bash
cd backend
# folder with fight/ and nonfight/ (or violence/ and noviolence/) sub-folders of short videos, e.g. the RWF-2000 layout.
# Use footage you are licensed to use.
python manage.py train-fight-model --data D:/datasets/RWF-2000 --pretrained-backbone --device cuda:0
# defaults: 15 epochs, batch 8, 4 decoding workers; RWF-2000's own train/val split is used when present
```

On a dataset without its own split, the command holds out 20% of the videos (stratified). It reports accuracy, precision, recall and F1, chooses the decision threshold on the hold-out set (never below 0.5), and writes `storage/models/video/fight_classifier_<version>.pt` with a `.json` metadata file including its SHA-256. Set `FIGHT_MODEL_PATH` (and optionally `FIGHT_MODEL_SHA256`) and restart. Weights are loaded with `torch.load(weights_only=True)` after the hash check, so no pickled code runs. `--pretrained-backbone` downloads ImageNet MobileNetV3 weights once; inference never downloads anything. Settings → Video anomaly detection shows the mode, version, hold-out results and activity.

A classifier score is a probability for review, not proof of an altercation; real cameras usually perform worse than the hold-out figures.

## 9. Face recognition (not included)

Cross-session identity recognition is **not implemented**. The product is designed to be useful without it. If it is ever added it must be a separately enabled, consent-based feature: enrolment only through an authorised workflow, comparison only against explicitly enrolled identities (never arbitrary members of the public), configurable thresholds with an *unverified* outcome, biometric templates stored separately and protected, consent/lawful-basis records with revocation and deletion, and no inference of identity, intent or suspiciousness from appearance. Check the applicable law first (in India, the Digital Personal Data Protection Act, 2023).

---

## 10. Security and privacy

- **Sessions**: signed JWT in an `httpOnly`, `SameSite=Lax` cookie (`Secure` in production); state-changing requests need the `X-VV-CSRF` header; sign-ins are throttled; sessions end immediately on deactivation, role change or password reset.
- **Tenant isolation** on every query and WebSocket; plan camera limits (`organizations.max_cameras`).
- **Rate limiting**: per-address sliding window (`RATE_LIMIT_PER_MINUTE`, expensive endpoints cost more); put a proxy-level limit in front of multi-instance deployments.
- **Headers**: `nosniff`, `X-Frame-Options: DENY`, CSP on API responses, HSTS when `COOKIE_SECURE`, `no-store` on API responses; API docs disabled in production.
- **Evidence**: served only to operators/admins through authenticated routes with path-traversal protection; per-organization storage limits; retention (`snapshot_retention_days`); audited deletion by administrators; never sent to notification channels or the cloud.
- **Secrets**: camera sources and integration secrets encrypted at rest (key derived from `SECRET_KEY`; rotating it requires re-entering them); never logged or returned.
- **Audit log**: sign-ins, settings, cameras, zones, locations, users, rules, channels, schedules, ML training, event corrections, visit links, occupancy changes, alert reviews, exports, evidence deletion, retention runs.
- **Retention** (hourly): snapshots, optional event expiry, closed alerts (`alert_retention_days`), old delivery/outbox rows.
- **Backups**: back up the PostgreSQL database (`pg_dump`, daily, encrypted, off-site) and the `storage` volume (evidence images, model artifacts). Restore = database restore + volume restore; `SECRET_KEY` must be the same to decrypt stored camera sources and channel settings, so keep it in your secret manager.

**Your obligations.** Use VIAHIND Vision only on cameras you are authorised to operate, display clear signage, limit access, keep retention short and follow applicable data-protection law.

---

## 11. Tests

```bash
cd backend && python -m pytest tests -q
# optional end-to-end check with the real detector (no real footage needed):
VV_TEST_MODEL_PATH=/path/to/yolo11n.pt python -m pytest tests/test_yolo_integration.py

cd frontend && npx tsc --noEmit && npm test && npm run build
```

CI (`.github/workflows/ci.yml`) runs the backend tests, migrations up/down/up on PostgreSQL 16, and the frontend typecheck, tests and build. Tests use synthetic fixtures only.

---

## 12. Known limitations

- **Occlusion and groups**: people walking very close together can merge into one track (undercount); long occlusions can split a track (possible uncertain events). Counts are estimates; reconcile occupancy with head counts.
- **Multiple entrances**: every doorway needs its own counting camera; overlapping counting cameras on one door double-count; uncounted doors cause occupancy drift.
- **Dwell times** restart when the tracker loses a person, so they are lower bounds.
- **Visits** are linked only by tracker continuity or by an operator; most exits stay unmatched, so visit durations are indicative.
- **One process per site** runs the camera workers; rate limiting is per process.
- **CPU inference** with `yolo11n` handles roughly 5–10 frames/s per camera; use `DETECTION_DEVICE=cuda:0` for several cameras.
- **Cloud sync** carries events (and corrections) only; alerts, zones and evidence stay at the edge. Camera IDs are unique across the whole installation.
- **Timezone** is per organization, not per location.
- **Billing** is limited to plan name and camera limit fields; no payment provider is integrated.
