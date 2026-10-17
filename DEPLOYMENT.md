# Deploying VIAHIND Vision on the internet

This guide covers putting a PG / hostel / office installation online so the owner can open
`https://pg.example.com` from anywhere, where every piece of data is stored, and how to keep it safe.

## 1. Where the processing runs: on-site, not in a data centre

The cameras are on the premises' local network (RTSP over Wi-Fi / LAN / NVR). Video analysis
(person detection, counting, zones, fight model) needs the full video stream, so it runs on a
computer **at the premises**. Only the website traffic goes over the internet.

```
 PG premises                                              Internet
 ┌────────────────────────────────────────────────┐
 │ cameras / NVR ──RTSP──► server (mini PC / PC)  │        owner / warden phone or laptop
 │                          ├─ backend + AI       │  HTTPS  https://pg.example.com
 │                          ├─ website            │◄──────── (Cloudflare Tunnel or
 │                          ├─ PostgreSQL         │           port forwarding + Caddy)
 │                          └─ evidence storage   │
 └────────────────────────────────────────────────┘
          alerts ──► email (your mail server) / Telegram ──► owner
```

Why not a cloud server (AWS, DigitalOcean…) running the AI?
- 16 cameras need 30–60 Mbit/s of **upload** around the clock; most PG broadband connections cannot sustain this.
- Cameras would have to be exposed to the internet (a common way CCTV systems get hacked).
- A cloud GPU server costs about ₹15,000–40,000 per month; a mini PC at the PG is a one-time cost.
- Footage of residents stays on the premises, which is easier to justify under India's DPDP Act.

For several PGs with one central dashboard, run each PG in `DEPLOYMENT_MODE=edge` and one cloud
server in `cloud` mode (README §1). Events are synchronised; images and camera passwords stay at each PG.

## 2. Where all data is stored

Everything lives on the on-site server, in Docker volumes:

| Data | Where | Size (typical PG) | Kept for |
|---|---|---|---|
| Database: users, cameras, guard posts, entry/exit log, alerts, incidents, audit log, settings, encrypted mail/Telegram secrets | Docker volume `pgdata` (PostgreSQL 16) | < 1 GB per year | events: forever by default (Settings → Data retention); closed alerts 180 days |
| Evidence snapshots (one photo per entry/exit or alert, never continuous video) | Docker volume `storage` → `/app/storage/snapshots` | ~60 KB each; 2,000 events/day ≈ 3.5 GB / month | 30 days (Settings → Event evidence), capped at the storage limit (default 2 GB) |
| Trained "unusual pattern" models | `storage` → `/app/storage/models` | a few MB | until retrained |
| AI model weights (YOLO, fight classifier) | `./models` folder, mounted read-only | ~20–40 MB | replaced on update |
| HTTPS certificates | Docker volume `caddy_data` | tiny | renewed automatically |
| Secrets (SECRET_KEY, DB password) | `backend/.env` and `./.env` files | tiny | **back these up**: without SECRET_KEY, stored mail/Telegram settings cannot be decrypted |
| Live video | not stored | n/a | only in memory while being analysed |

Disk: a 256 GB SSD is plenty for 16 cameras with 30-day evidence retention. The server stops saving
snapshots before the disk fills (`MIN_FREE_DISK_MB`) and shows a warning instead of crashing.

## 3. Hardware

| Cameras | Server | Notes |
|---|---|---|
| 1–4 | Mini PC, Intel i5 (10th gen+) / Ryzen 5, 16 GB RAM, 256 GB SSD (₹30–45k) | CPU detection, `yolo11n` |
| 5–16 | PC with NVIDIA GPU (RTX 3060 or better), 16–32 GB RAM, 512 GB SSD | GPU needed for 16 cameras with fight detection |

8 GB RAM is not enough to run all models reliably. Put the server on a UPS, wire it to the router with
Ethernet, and set the BIOS to power on after a power cut.

## 4. Going live, step by step (Ubuntu Server 24.04 on the on-site PC)

### 4.1 Install Docker and get the code
```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER && newgrp docker
sudo git clone https://github.com/Anshuman776/viahind_vision.git /opt/viahind_vision
sudo chown -R $USER /opt/viahind_vision && cd /opt/viahind_vision
git checkout vision-v1
```

### 4.2 Copy the AI models
```bash
mkdir -p models/video
# from the development PC (backend/storage/models/... and the person counter folder):
#   yolo11n.pt                                  -> models/yolo11n.pt
#   fight_classifier_<version>.pt and .json     -> models/video/
sha256sum models/video/*.pt      # put this value in FIGHT_MODEL_SHA256 below
```

### 4.3 Settings
```bash
cp deploy/compose.env.example .env                        # POSTGRES_PASSWORD, SITE_ADDRESS, model file names
cp deploy/backend.env.production.example backend/.env     # SECRET_KEY, PUBLIC_BASE_URL, FIGHT_MODEL_SHA256
openssl rand -base64 32                                   # use for POSTGRES_PASSWORD
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # use for SECRET_KEY
chmod 600 .env backend/.env
```

### 4.4 Choose how the internet reaches the server

**Option A: Cloudflare Tunnel (recommended for PG broadband: Jio, Airtel, ACT, BSNL).**
No public IP, no router changes, and nothing is opened on the PG network.
1. Add your domain to Cloudflare (free plan).
2. Cloudflare dashboard → Zero Trust → Networks → Tunnels → *Create tunnel* (Cloudflared) → copy the token.
3. In the tunnel, add a public hostname: `pg.example.com` → service `http://caddy:80`.
4. In `.env`: `SITE_ADDRESS=:80` and `TUNNEL_TOKEN=<token>`.
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile tunnel up -d --build
```

**Option B: public IP / port forwarding.**
1. DNS: an `A` record `pg.example.com` → the PG's public IP (ask the ISP for a static IP).
2. Router: forward TCP 80 and 443 (and UDP 443) to the server.
3. In `.env`: `SITE_ADDRESS=pg.example.com`, `ACME_EMAIL=you@example.com`. Caddy obtains the HTTPS certificate automatically.
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

### 4.5 First login and setup
```bash
docker compose exec backend python manage.py create-user admin --role admin
```
Open `https://pg.example.com`, then:
1. **Settings → Cameras**: add each camera (RTSP address from the camera or NVR app).
2. **Live Cameras**: draw the counting line on the gate camera, plus restricted / monitored zones.
3. **Guard Room**: give each guard its post (Main gate, Corridor, Common room, Restricted area…).
4. **Settings → Locations**: gate timings (curfew) and capacity.
5. **Settings → Mail server** (Gmail App Password) → *Send test*; **Notifications**: the owner's email and Telegram.
6. **Guard Room → Head guard settings**: turn on the daily briefing.

### 4.6 Backups (do not skip)
```bash
sh deploy/backup.sh /mnt/backup            # database + snapshots + backend/.env, keeps 14 days
crontab -e
30 2 * * * cd /opt/viahind_vision && sh deploy/backup.sh /mnt/backup >> /opt/viahind_vision/backups.log 2>&1
```
Copy `/mnt/backup` off the machine regularly: a USB disk kept elsewhere, a NAS, or cloud storage
(e.g. `rclone sync /mnt/backup gdrive:viahind-backup`). Practise a restore once (commands in `deploy/backup.sh`).

## 5. Updating
```bash
cd /opt/viahind_vision
sh deploy/backup.sh
git pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build   # migrations run on start
```

## 6. GPU (5–16 cameras)
Install the NVIDIA driver and the NVIDIA Container Toolkit, then in `backend/Dockerfile` install the CUDA
PyTorch wheels (replace `.../whl/cpu` with `.../whl/cu121`) and add to the backend service:
```yaml
    deploy:
      resources:
        reservations:
          devices: [{ driver: nvidia, count: 1, capabilities: [gpu] }]
```
Then set `DETECTION_DEVICE=cuda:0`, and optionally `PERSON_MODEL_FILE=yolo11s.pt` for more accurate person detection.

## 7. Production checklist
- [ ] `SECRET_KEY` and `POSTGRES_PASSWORD` are long random values; `.env` files are `chmod 600` and never committed
- [ ] The site opens only over `https://`; ports 8000, 3000 and 5432 are not reachable from outside (`docker compose ps`)
- [ ] Each camera has its own strong password; camera and NVR admin pages are not port-forwarded
- [ ] The admin account uses a strong password; operators and wardens use their own operator accounts
- [ ] Mail server *Send test* works and Telegram receives the channel test
- [ ] Nightly backup runs, a copy leaves the building, and a restore was tested
- [ ] Server on a UPS; BIOS set to power on after a power cut; Docker restarts the services (`restart: unless-stopped`)
- [ ] Residents are informed about CCTV and AI monitoring (notice at the entrance) and evidence retention is as short as practical
