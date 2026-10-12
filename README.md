# VIAHIND Vision

VIAHIND Vision is a high-performance CCTV video analytics and security alert management platform designed for multi-floor PG (Paying Guest) facilities. It provides edge AI detection for physical altercations, suspicious loitering, and perimeter breaches, paired with a command-center interface for security supervisors.

---

## 1. Project Structure

The project is divided cleanly into dedicated `frontend` and `backend` workspaces:

```
viahind-vision/
├── frontend/                       # Next.js 16 + TypeScript + Vanilla CSS
│   ├── .env.local                  # Frontend environment configuration
│   ├── .env.example                # Frontend template
│   ├── app/
│   │   ├── layout.tsx              # Root layout with dark command-center theme
│   │   ├── page.tsx                # Redirects to /alerts
│   │   ├── alerts/page.tsx         # Security Alerts Command Center & Split View
│   │   ├── monitoring/page.tsx     # Live Multi-Floor CCTV Matrix
│   │   └── overview/page.tsx       # AI Model Telemetry & Facility Analytics
│   ├── components/
│   │   ├── AlertCard.tsx           # Event type, camera, floor, severity, AI score pill
│   │   ├── AlertList.tsx           # Status tabs, search, floor, date & severity filters
│   │   ├── IncidentDetail.tsx      # Video evidence area, metadata, AI meter, timeline
│   │   ├── IncidentTimeline.tsx    # Chronological audit trail (system, model, user)
│   │   ├── ReviewActions.tsx       # Acknowledge, Confirm Incident, Dismiss & notes
│   │   ├── Sidebar.tsx             # Operations navigation & facility switcher
│   │   └── CameraGrid.tsx          # Multi-floor CCTV feed matrix
│   ├── data/
│   │   └── mockAlerts.ts           # Labeled simulated synthetic dataset
│   ├── types/
│   │   └── alert.ts                # TypeScript interfaces for alerts & review actions
│   └── test/
│       ├── setup.ts                # Vitest + Testing Library setup
│       └── Alerts.test.tsx         # Unit tests for filters, details, and review actions
│
├── backend/                        # FastAPI Backend & Stream Broker
│   ├── .env                        # Backend environment configuration
│   ├── .env.example                # Backend environment template
│   ├── config.py                   # Settings loader & environment parser
│   ├── main.py                     # FastAPI application entry point with CORS
│   ├── websocket.py                # WebSocket real-time connection manager
│   ├── requirements.txt            # Python dependencies
│   ├── routers/
│   │   ├── alerts.py               # Alert listing, detail, and review action routes
│   │   └── cameras.py              # Camera inventory and floor feeds
│   ├── models/
│   │   └── alert.py                # Pydantic schemas for alerts and review requests
│   └── edge-agent/                 # CCTV Ingestion & AI Detection
│       ├── rtsp_reader.py          # RTSP stream reader
│       ├── fight_detector.py       # MobileNetV3 optical flow fight classifier
│       └── event_manager.py        # Edge event dispatcher
│
├── migrations/                     # Database migrations
├── tests/                          # Root integration tests
└── docker-compose.yml              # Container orchestration
```

---

## 2. Backend Setup & `.env` Configuration

The backend is configured via `backend/.env`.

### Environment Variables in `backend/.env`:
| Variable | Description | Default |
| :--- | :--- | :--- |
| `APP_NAME` | Service title | `"VIAHIND Vision Security Analytics API"` |
| `APP_ENV` | Environment mode | `development` |
| `DEBUG` | Enable debug logs | `True` |
| `HOST` / `PORT` | Server host and port | `0.0.0.0` / `8000` |
| `API_V1_PREFIX` | Base REST prefix | `/api/v1` |
| `SECRET_KEY` | JWT signing secret | Secure random string |
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://viahind_user:...@localhost:5432/...` |
| `REDIS_URL` | Redis cache and broker | `redis://localhost:6379/0` |
| `CORS_ORIGINS` | Permitted frontend origins | `http://localhost:3000,http://127.0.0.1:3000` |
| `RTSP_BROKER_URL`| RTSP stream base endpoint | `rtsp://localhost:8554/live` |
| `FIGHT_DETECTOR_MODEL`| Model architecture | `VIAHIND-FightClassifier-MobileNetV3` |
| `FIGHT_DETECTOR_VERSION`| Model release version | `v2.4.1-edge` |
| `FIGHT_CONFIDENCE_THRESHOLD`| Altercation alert threshold | `0.75` (75%) |
| `ACTIVE_FACILITY_ID`| PG block identifier | `FAC-PG-BLOCK-A` |

### How to Run Backend:
1. Navigate to `backend/`:
   ```bash
   cd backend
   ```
2. Create and activate a Python virtual environment:
   ```bash
   python -m venv .venv
   # Windows:
   .venv\Scripts\activate
   # Linux/macOS:
   source .venv/bin/activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Verify or adjust `backend/.env` as needed.
5. Launch the FastAPI server:
   ```bash
   uvicorn main:app --reload --host 0.0.0.0 --port 8000
   ```
6. API Documentation will be available at:
   - Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs)
   - Health check: [http://localhost:8000/health](http://localhost:8000/health)

---

## 3. Frontend Setup & `.env.local`

The frontend connects to the backend using `frontend/.env.local`:
```env
NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
NEXT_PUBLIC_WS_URL=ws://localhost:8000/ws/alerts
NEXT_PUBLIC_DEFAULT_FACILITY=FAC-PG-BLOCK-A
```

### How to Run Frontend:
1. Navigate to `frontend/`:
   ```bash
   cd frontend
   ```
2. Install dependencies:
   ```bash
   npm install --legacy-peer-deps
   ```
3. Start the dev server (automatically binds to `0.0.0.0` for LAN smartphone access):
   ```bash
   npm run dev
   ```
4. Access the interface:
   - Security Alerts Command Center: [http://localhost:3000/alerts](http://localhost:3000/alerts)
   - Live CCTV Matrix: [http://localhost:3000/monitoring](http://localhost:3000/monitoring)
   - Phone CCTV Streamer: [http://localhost:3000/streamer](http://localhost:3000/streamer)
   - Analytics & Telemetry: [http://localhost:3000/overview](http://localhost:3000/overview)

5. Run test suite:
   ```bash
   npm test
   ```

---

## 4. Connecting Smartphone as CCTV Camera (LAN / Wi-Fi)

VIAHIND Vision allows any smartphone to function as an edge CCTV camera by scanning a QR code or visiting `/streamer` over Wi-Fi.

### Requirements:
1. **Same Wi-Fi Network**: Laptop and smartphone must be on the same Wi-Fi router, or connected via Windows Mobile Hotspot. Mobile Data (4G/5G) cannot reach private LAN IP addresses.
2. **Dynamic LAN Detection**: The host URL is auto-detected dynamically from `/api/network-info` (e.g. `10.167.189.1:3000`) and can be manually overridden in the UI modal if desired.
3. **Windows Defender Firewall Setup**:
   Allow inbound TCP traffic on ports 3000 (frontend) and 8000 (backend) in **PowerShell (Run as Administrator)**:
   ```powershell
   New-NetFirewallRule -DisplayName "VIAHIND Vision Frontend" -Direction Inbound -LocalPort 3000 -Protocol TCP -Action Allow
   New-NetFirewallRule -DisplayName "VIAHIND Vision Backend" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow
   ```

