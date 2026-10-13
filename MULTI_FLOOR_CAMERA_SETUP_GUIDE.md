> **Superseded.** This guide describes the earlier multi-floor CCTV matrix UI, which has been replaced by the
> VIAHIND Vision PG Surveillance System. Cameras are now added in **Settings → Cameras**; see `README.md`
> ("Connecting cameras"). Kept for reference only.

# Multi-Floor & Multi-Camera Setup Guide: VIAHIND Vision

This comprehensive guide explains how to add and manage cameras across multiple floors in **VIAHIND Vision**, specifically focusing on:
1. Adding cameras to a specific floor (e.g., **Floor 1**).
2. Adding **multiple cameras** on the same floor (e.g., multiple corridor angles, entrances, and staircases).
3. Managing different camera types:
   - **Smartphones as CCTV** (via Web Streamer or IP Webcam app)
   - **Physical IP/CCTV Cameras** (via RTSP streams)
4. Adding entirely new floors (e.g., Floor 4, Floor 5) if your building expands.

---

## 1. System Architecture & Hierarchy

In VIAHIND Vision, video analytics and alert monitoring follow a strict spatial hierarchy:

```
Facility (e.g., FAC-PG-BLOCK-A)
 ├── Basement
 ├── Ground Floor
 ├── Floor 1  <────────────────────────── [Our Target Floor]
 │    ├── CAM-F1-CORR-01 (Corridor East)
 │    ├── CAM-F1-CORR-02 (Corridor West)
 │    ├── CAM-F1-STAIR-01 (Staircase A)
 │    └── CAM-F1-LOUNGE-01 (Common Lounge)
 ├── Floor 2
 ├── Floor 3
 └── Rooftop
```

Every camera requires:
* **Unique Camera ID**: A string identifier following the convention `CAM-<FLOOR>-<ZONE>-<NUMBER>` (e.g., `CAM-F1-CORR-01`).
* **Name**: Human-readable label (e.g., `Floor 1 Corridor East`).
* **Floor**: Associated floor identifier (e.g., `Floor 1`).
* **Location**: Specific room, door, or wing (e.g., `Near Room 104, East Wing`).
* **Stream Source**: WebSocket live relay, MJPEG IP stream, or RTSP stream URL.

---

## 2. Method 1: Adding Multiple Cameras via Web Dashboard (UI)

You can add multiple cameras directly in the browser while the system is running:

### Step 1: Open Live Monitoring
1. Start your backend (`uvicorn main:app --reload` on port 8000).
2. Start your frontend (`npm run dev` on port 3000).
3. Open `http://localhost:3000/monitoring` in your browser.

### Step 2: Open the "Add Camera" Modal
1. In the upper-right corner of the **CCTV Matrix**, click the **`+ Add Camera`** button.
2. The modal **"Connect Live Camera Feed"** will appear.

### Step 3: Add Camera #1 for Floor 1
Fill in the form fields:
* **Camera ID**: `CAM-F1-CORR-01`
* **Camera Name**: `Floor 1 Corridor East`
* **Floor**: Select `Floor 1` from the dropdown
* **Zone / Location**: `Corridor near Room 102 (East Wing)`
* **Connection Method**: 
  * Choose **"Smartphone Web Streamer"** (if using phone browser), OR
  * Choose **"IP Webcam App (MJPEG / RTSP)"** and enter the stream URL (e.g., `http://192.168.1.55:8080/video`)
* Click **"Connect Camera"**.

### Step 4: Add Camera #2 for Floor 1
1. Click **`+ Add Camera`** again.
2. Fill in the details for the second camera on the same floor:
   * **Camera ID**: `CAM-F1-CORR-02` *(Must be different from Camera #1)*
   * **Camera Name**: `Floor 1 Corridor West`
   * **Floor**: Select `Floor 1`
   * **Zone / Location**: `Corridor near Room 115 (West Wing)`
   * **Connection Method**: Choose desired stream type.
3. Click **"Connect Camera"**.

### Step 5: Filter by Floor 1
In the CCTV Matrix floor tabs bar, click **`Floor 1`**. 
The matrix will now isolate and display only the cameras installed on Floor 1.

---

## 3. Method 2: Connecting Smartphones as CCTV Cameras via QR Code & Browser

You can turn any smartphone into a live, high-definition CCTV camera streaming straight into VIAHIND Vision without installing mobile apps:

### How Host URL & QR Code Generation Works
1. **Dynamic Host Detection**: The system queries `/api/network-info` to automatically detect your computer's active Wi-Fi IPv4 address (e.g., `10.167.189.1`) and the current frontend port (e.g., `3000`).
2. **Zero Hardcoded IPs**: No stale or hardcoded IP addresses are used. If your laptop's Wi-Fi network or IP changes, the QR code and link update automatically.
3. **Manual Host Override**: In the **+ Connect Phone Camera** modal, you can manually override the host address (e.g., if you are connected to a specific mobile hotspot, VPN, or local domain name).
4. **Synchronized QR Code & Link**: The QR code encodes the exact URL displayed in the modal, complete with pre-configured parameters:
   ```
   http://<YOUR_PC_IP>:3000/streamer?id=CAM-F1-CORR-01&floor=Floor%201&name=...&loc=...
   ```
5. **One-Click Link Copying**: Click **"Copy Link"** to copy the full streamer URL to your clipboard.

### Network & Windows Firewall Requirements
* **Same Wi-Fi Network Required**: Both the laptop and smartphone must be on the same Wi-Fi router or connected via Windows Mobile Hotspot. Smartphones using **Cellular Data (4G/5G)** cannot route to private LAN IP addresses (e.g., `10.x.x.x` or `192.168.x.x`).
* **Next.js Bound to 0.0.0.0**: The frontend dev server is configured with `next dev -H 0.0.0.0` so it listens on all local network adapters.
* **Windows Defender Firewall Inbound Rules**: Windows Firewall blocks inbound LAN connections by default. Run the following in **PowerShell (Run as Administrator)**:
  ```powershell
  # Allow Frontend UI & Streamer (Port 3000)
  New-NetFirewallRule -DisplayName "VIAHIND Vision Frontend" -Direction Inbound -LocalPort 3000 -Protocol TCP -Action Allow

  # Allow Backend REST API & WebSocket Stream Broker (Port 8000)
  New-NetFirewallRule -DisplayName "VIAHIND Vision Backend" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow
  ```

### Step-by-Step Connection Instructions:
1. In the CCTV Matrix, click **`+ Connect Phone Camera`**.
2. Select or enter your camera details (e.g. `CAM-F1-CORR-01`, `Floor 1`).
3. Scan the generated QR code with your phone camera, or click **Copy Link** to send the URL to your phone.
4. On the phone, grant camera permissions when prompted.
5. Tap **"Start Live CCTV Broadcast"**.
6. The feed will appear in real time on the Command Center matrix card under Floor 1 at ~15 FPS!

---

## 4. Method 3: Registering Cameras via Backend REST API

If you have automated scripts, edge devices, or IP cameras, you can register them using the REST API:

### Endpoint:
`POST http://localhost:8000/api/v1/cameras/phone`

### Request Header:
`Content-Type: application/json`

### Example: Adding 3 Cameras to Floor 1

#### Camera 1: Corridor East
```bash
curl -X POST "http://localhost:8000/api/v1/cameras/phone" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "CAM-F1-CORR-01",
    "name": "Floor 1 Corridor East",
    "floor": "Floor 1",
    "location": "Boys Wing Corridor near Room 102",
    "stream_type": "browser_stream"
  }'
```

#### Camera 2: Corridor West
```bash
curl -X POST "http://localhost:8000/api/v1/cameras/phone" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "CAM-F1-CORR-02",
    "name": "Floor 1 Corridor West",
    "floor": "Floor 1",
    "location": "Boys Wing Corridor near Room 118",
    "stream_type": "browser_stream"
  }'
```

#### Camera 3: IP Webcam on Floor 1 Stairwell
```bash
curl -X POST "http://localhost:8000/api/v1/cameras/phone" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "CAM-F1-STAIR-01",
    "name": "Floor 1 Fire Staircase",
    "floor": "Floor 1",
    "location": "North Fire Stairwell Exit",
    "stream_type": "ip_webcam_mjpeg",
    "ip_stream_url": "http://192.168.1.45:8080/video"
  }'
```

### Python Registration Script:
```python
import requests

API_URL = "http://localhost:8000/api/v1/cameras/phone"

floor_1_cameras = [
    {
        "id": "CAM-F1-CORR-01",
        "name": "Floor 1 Corridor East",
        "floor": "Floor 1",
        "location": "Near Room 105",
        "stream_type": "browser_stream",
    },
    {
        "id": "CAM-F1-CORR-02",
        "name": "Floor 1 Corridor West",
        "floor": "Floor 1",
        "location": "Near Room 120",
        "stream_type": "browser_stream",
    },
    {
        "id": "CAM-F1-LOUNGE-01",
        "name": "Floor 1 Common Study Room",
        "floor": "Floor 1",
        "location": "Central Common Hall",
        "stream_type": "browser_stream",
    },
]

for cam in floor_1_cameras:
    res = requests.post(API_URL, json=cam)
    print(f"Registered {cam['id']}: status code {res.status_code}")
```

---

## 5. Method 4: Permanently Pre-configuring Cameras in Backend Code

To have cameras permanently present whenever the backend restarts, edit `backend/routers/cameras.py`:

Open `backend/routers/cameras.py` and modify the `CONNECTED_CAMERAS` list:

```python
CONNECTED_CAMERAS: List[CameraStatusModel] = [
    # --- GROUND FLOOR ---
    CameraStatusModel(
        id="CAM-G-LOBBY-01",
        name="Ground Reception Turnstile",
        floor="Ground Floor",
        location="Main Security Turnstile & Lobby",
        status="online",
        fps=30,
        stream_type="rtsp",
        is_phone_camera=False,
        has_active_alert=False,
    ),

    # --- FLOOR 1: CAMERA 1 ---
    CameraStatusModel(
        id="CAM-F1-CORR-01",
        name="Floor 1 Main Corridor East",
        floor="Floor 1",
        location="Wing East near Room 105",
        status="online",
        fps=30,
        stream_type="rtsp",
        is_phone_camera=False,
        has_active_alert=True,
    ),

    # --- FLOOR 1: CAMERA 2 ---
    CameraStatusModel(
        id="CAM-F1-CORR-02",
        name="Floor 1 Main Corridor West",
        floor="Floor 1",
        location="Wing West near Room 120",
        status="online",
        fps=30,
        stream_type="rtsp",
        is_phone_camera=False,
        has_active_alert=False,
    ),

    # --- FLOOR 1: CAMERA 3 ---
    CameraStatusModel(
        id="CAM-F1-STAIR-01",
        name="Floor 1 Emergency Staircase",
        floor="Floor 1",
        location="Emergency Stairwell North Wing",
        status="online",
        fps=30,
        stream_type="rtsp",
        is_phone_camera=False,
        has_active_alert=False,
    ),

    # --- FLOOR 1: CAMERA 4 ---
    CameraStatusModel(
        id="CAM-F1-LOUNGE-01",
        name="Floor 1 Common Study Room",
        floor="Floor 1",
        location="Resident Study Lounge",
        status="online",
        fps=30,
        stream_type="rtsp",
        is_phone_camera=False,
        has_active_alert=False,
    ),

    # --- FLOOR 2 ---
    CameraStatusModel(
        id="CAM-F2-STAIR-02",
        name="Floor 2 Emergency Fire Stair",
        floor="Floor 2",
        location="Emergency Fire Stairwell B",
        status="online",
        fps=30,
        stream_type="rtsp",
        is_phone_camera=False,
    ),
]
```

---

## 6. Method 5: Updating Frontend Mock Cameras & AI Alerts

If you want the frontend to display multiple Floor 1 cameras in offline or demo mode:

### 1. Update `frontend/components/CameraGrid.tsx`
Edit `defaultMockCameras` (around line 35):

```typescript
const defaultMockCameras: CameraItem[] = [
  // Floor 1 - Camera 1
  {
    id: 'CAM-F1-CORR-01',
    name: 'Floor 1 Corridor East',
    floor: 'Floor 1',
    location: 'Boys Wing Corridor near Room 105',
    status: 'online',
    fps: 30,
    hasActiveAlert: true,
  },
  // Floor 1 - Camera 2
  {
    id: 'CAM-F1-CORR-02',
    name: 'Floor 1 Corridor West',
    floor: 'Floor 1',
    location: 'Boys Wing Corridor near Room 120',
    status: 'online',
    fps: 30,
    hasActiveAlert: false,
  },
  // Floor 1 - Camera 3
  {
    id: 'CAM-F1-STAIR-01',
    name: 'Floor 1 Stairwell North',
    floor: 'Floor 1',
    location: 'Stairwell A Wing 1',
    status: 'online',
    fps: 28,
  },
  // ... other floors
];
```

### 2. Connect Floor 1 Cameras to AI Alerts in `frontend/data/mockAlerts.ts`
When an AI fight alert triggers, it references the specific camera on Floor 1:

```typescript
{
  id: 'ALT-PG-2026-081',
  camera: {
    id: 'CAM-F1-CORR-01',
    name: 'Floor 1 Main Corridor East',
    location: 'Boys Wing Corridor near Room 105',
    floor: 'Floor 1',
    rtspStreamUrl: 'rtsp://edge-agent.local:8554/live/cam-f1-corr-01',
  },
  eventType: 'Physical Altercation',
  severity: 'critical',
  status: 'pending',
  // ...
}
```

---

## 7. How to Add a Brand-New Floor (e.g. Floor 4 or Floor 5)

If your facility has additional floors not currently in the default list:

### Step 1: Update TypeScript Types
In `frontend/types/alert.ts`:
```typescript
export type FloorIdentifier = 
  | 'Basement' 
  | 'Ground Floor' 
  | 'Floor 1' 
  | 'Floor 2' 
  | 'Floor 3' 
  | 'Floor 4'   // <-- ADD NEW FLOOR
  | 'Floor 5'   // <-- ADD NEW FLOOR
  | 'Rooftop';
```

### Step 2: Update UI Dropdowns in `frontend/components/CameraGrid.tsx`
In `CameraGrid.tsx`, update the `floors` array:
```typescript
const floors: Array<FloorIdentifier | 'all'> = [
  'all',
  'Basement',
  'Ground Floor',
  'Floor 1',
  'Floor 2',
  'Floor 3',
  'Floor 4',    // <-- ADD HERE
  'Floor 5',    // <-- ADD HERE
  'Rooftop',
];
```

And in the floor selection dropdown inside the `showAddModal` JSX:
```tsx
<select
  value={phoneFloor}
  onChange={(e) => setPhoneFloor(e.target.value as FloorIdentifier)}
>
  <option value="Basement">Basement</option>
  <option value="Ground Floor">Ground Floor</option>
  <option value="Floor 1">Floor 1</option>
  <option value="Floor 2">Floor 2</option>
  <option value="Floor 3">Floor 3</option>
  <option value="Floor 4">Floor 4</option>
  <option value="Floor 5">Floor 5</option>
  <option value="Rooftop">Rooftop</option>
</select>
```

### Step 3: Update `frontend/app/streamer/page.tsx`
Add the new floor to the dropdown options in `streamer/page.tsx`:
```tsx
<select value={floor} onChange={(e) => setFloor(e.target.value)}>
  <option value="Floor 1">Floor 1</option>
  <option value="Floor 2">Floor 2</option>
  <option value="Floor 3">Floor 3</option>
  <option value="Floor 4">Floor 4</option>
  <option value="Floor 5">Floor 5</option>
  <option value="Ground Floor">Ground Floor</option>
  <option value="Basement">Basement</option>
  <option value="Rooftop">Rooftop</option>
</select>
```

---

## 8. Physical IP / CCTV Camera Ingestion (RTSP Streams)

For enterprise CCTV cameras (Hikvision, Dahua, Axis, CP Plus):

1. **RTSP URL Format**:
   - Hikvision: `rtsp://admin:password@192.168.1.64:554/Streaming/Channels/101`
   - Dahua: `rtsp://admin:password@192.168.1.65:554/cam/realmonitor?channel=1&subtype=0`
   - Generic: `rtsp://<user>:<password>@<camera-ip>:554/live`

2. **Connecting to VIAHIND Vision Edge Agent**:
   In `backend/edge-agent/rtsp_reader.py`:
   ```python
   reader = RTSPReader(
       camera_id="CAM-F1-CORR-01",
       stream_url="rtsp://192.168.1.64:554/Streaming/Channels/101"
   )
   reader.connect()
   ```

3. **Multi-Camera AI Processing Pipeline**:
   The edge agent can ingest multiple cameras from Floor 1 in parallel threads or async workers, extracting frames every 50ms and evaluating them with the `FightDetector` classifier:
   ```python
   # Frame evaluation loop
   inference = fight_detector.predict_clip(frames)
   if inference["is_fight"] and inference["confidence_score"] >= 0.75:
       # Dispatches alert tagged with CAM-F1-CORR-01 and Floor 1
       event_manager.dispatch_alert(camera_id="CAM-F1-CORR-01", floor="Floor 1")
   ```

---

## 9. Verification & Troubleshooting Checklist

| Test Item | Verification Command / Step | Expected Result |
| :--- | :--- | :--- |
| **1. List Registered Cameras** | `curl http://localhost:8000/api/v1/cameras` | Returns JSON array including all Floor 1 cameras |
| **2. Filter by Floor in UI** | Navigate to `/monitoring` and click **"Floor 1"** | Only cameras with `floor: "Floor 1"` are displayed |
| **3. Streamer Connection** | Open `/streamer` on smartphone and start broadcast | Matrix card switches to live video frames at ~15 FPS |
| **4. AI Alert Routing** | On `/streamer`, click **"Simulate Violent Motion"** | Real-time red alert modal pops up in dashboard tagged with Floor 1 and Camera ID |
| **5. Delete Camera** | In `/monitoring`, click red trash icon on phone camera | Camera disconnects and disappears from Floor 1 list |

---

*Authored for VIAHIND Vision Security Command Center.*
