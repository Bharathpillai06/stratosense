# StratoSense

Atmospheric analysis dashboard for **radiosonde flights** (SondeHub) and, when configured, **Synoptic** ground-station observations. The backend derives vertical profiles, stability metrics, and plain-language summaries; the frontend combines a Leaflet live map, a Three.js altitude column, and Chart.js soundings and wind panels.

## Features

- **Landing page** — Home at `/` with status and link to the dashboard
- **Live map (Leaflet)** — Active radiosondes worldwide; optional Synoptic stations in the current viewport (requires `SYNOPTIC_TOKEN`)
- **Balloon or station mode** — Click a sonde or station on the map, or enter a serial / station ID. Stations use a hybrid vertical profile built from surface and time-series data
- **3D altitude column (Three.js)** — Stylized Earth column with the balloon or station profile, synchronized with scrubbers
- **Atmospheric sounding** — Temperature and dewpoint vs altitude (balloon path or station snapshot)
- **Wind barbs** — Wind profile by altitude band
- **Score card** — CAPE, CIN, lapse rate, tropopause, precipitable water, storm risk; for balloons, a **Forecast** section from `/balloon/<serial>/forecast`
- **Flight timeline** — `FlightScrubber` replays a radiosonde ascent; `StationScrubber` steps through station time steps and vertical levels
- **Updates** — Backend refreshes the SondeHub cache every **10 seconds** and emits Socket.IO `balloons_update`. The Vite dev UI polls REST endpoints about every **5 seconds** (it does not use a Socket.IO client)

## Architecture

```text
SondeHub API ──┐
               ├──► Flask + Flask-SocketIO (port 8080) ──► React + Vite (port 5173, proxied API)
Synoptic API ──┘      ├── data_pipeline (balloons, stations, analysis)
   (optional)          ├── atmosphere (model profile API)
                        └── sdr (optional local RTL-SDR status)
```

| Layer | Technology |
| --- | --- |
| Radiosonde data | [SondeHub](https://sondehub.org) (no API key for read access) |
| Station data | [Synoptic Data API](https://synopticdata.com/) — token required for map search, weather, and station profiles |
| Backend | Python 3, Flask, Flask-SocketIO, Requests, python-dotenv |
| Frontend | React 19, Vite 8, React Router 7 |
| Map | Leaflet (loaded from CDN in `Globe.jsx`) |
| Charts / 3D | Chart.js 4, react-chartjs-2, Three.js |

## Requirements

### Backend (Python)

- Python 3.9+
- `flask`, `flask-socketio`, `requests`, `python-dotenv`

Optional for tests:

- `pytest`

### Frontend (Node)

- Node.js 20+
- npm 9+

Dependencies are pinned in [frontend/package.json](frontend/package.json).

## Setup & running

### 1. Clone the repo

```bash
git clone https://github.com/rishivarshil/stratosense.git
cd stratosense
```

### 2. Synoptic token (optional but needed for stations)

For **radiosondes only**, you can skip this. To show ground stations on the map and use station profiles, get a token from [Synoptic Weather API](https://synopticdata.com/weatherapi/), then add to a `.env` file at the **repository root**:

```env
SYNOPTIC_TOKEN=your_token_here
```

`python-dotenv` loads this when you start the server from `src/`. You can also set `SYNOPTIC_TOKEN` in your environment instead.

### 3. Python virtual environment

**Windows PowerShell**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If activation is blocked:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

**macOS / Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 4. Install backend dependencies

From the repo root:

```bash
pip install flask flask-socketio requests python-dotenv
```

For backend tests:

```bash
pip install pytest
```

### 5. Start the backend

```bash
cd src
python data_pipeline.py
```

The API listens on `http://127.0.0.1:8080`. A background thread polls SondeHub every 10 seconds and updates the in-memory balloon cache.

### 6. Install and run the frontend

Second terminal, from repo root:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173` — landing page at `/`, dashboard at `/dashboard`. The dev server proxies API paths to port 8080 (see [frontend/vite.config.js](frontend/vite.config.js)).

### 7. Wrap-up

You should have:

1. Backend: venv active, `python data_pipeline.py` running from `src`
2. Frontend: `npm run dev` from `frontend`

```bash
deactivate
```

when finished with the venv.

## API endpoints

### Balloons (SondeHub)

| Method | Path | Description |
| --- | --- | --- |
| GET | `/balloons` | Cached active balloons + metadata |
| GET | `/balloon/<serial>` | Flight path points |
| GET | `/balloon/<serial>/analysis` | Lapse rate, tropopause, winds, CAPE/CIN, PW, storm risk |
| GET | `/balloon/<serial>/forecast` | Plain-language forecast JSON |
| GET | `/balloon/<serial>/telemetry` | Extended telemetry summary and frames |

### Stations & weather (Synoptic — requires `SYNOPTIC_TOKEN`)

| Method | Path | Description |
| --- | --- | --- |
| GET | `/weather/<stid>` | Latest observation for station ID |
| GET | `/weather/<stid>/timeseries` | Time series (`recent`, `vars` query params) |
| GET | `/weather/stations/search` | Stations by viewport / radius (`lat`, `long`, `radius`, `limit`, …) |
| GET | `/station/<stid>/profile` | Hybrid vertical snapshot for charts / 3D |
| GET | `/station/<stid>/analysis` | Same metrics as balloon analysis for a station snapshot |
| GET | `/station/<stid>/hybrid` | Full hybrid dataset (snapshots over time) |

### Other

| Method | Path | Description |
| --- | --- | --- |
| GET | `/status` | Server health, balloon count, `synoptic_available` flag |
| GET | `/atmosphere/profile` | Full modeled profile (surface + optional balloon nudging) |
| GET | `/atmosphere/at/<altitude_m>` | Conditions at one altitude |
| GET | `/atmosphere/density_altitude` | Density altitude from surface obs |
| GET | `/atmosphere/status` | Short model / assimilation status |
| GET | `/sdr/status` | Local RTL-SDR / `radiosonde_auto_rx` telemetry vs SondeHub (optional hardware) |

**WebSocket:** Socket.IO event `balloons_update` broadcasts the latest balloon list after each SondeHub poll. Clients may subscribe; the stock dashboard relies on HTTP polling.

## Atmospheric calculations

Core radiosonde metrics are computed in [src/data_pipeline.py](src/data_pipeline.py) (and helpers): lapse rate, tropopause, CAPE/CIN, wind profile, precipitable water, storm risk. Station vertical structure uses [src/interpolation.py](src/interpolation.py) and related assimilation helpers. The [src/atmosphere.py](src/atmosphere.py) blueprint adds a separate analytical profile API for drone-style queries.

## Project structure

```text
stratosense/
├── src/
│   ├── data_pipeline.py      # Flask app: balloons, Synoptic, station hybrid, analysis
│   ├── atmosphere.py         # Atmospheric model blueprint
│   ├── sdr_integration.py    # Optional local SDR status blueprint
│   ├── interpolation.py      # Vertical profile construction
│   ├── assimilation.py       # Observation handling for profiles
│   ├── test_data_pipeline.py
│   ├── test_assimilation.py
│   └── test_person4.py
└── frontend/
    ├── package.json
    ├── vite.config.js
    └── src/
        ├── App.jsx
        ├── assets/
        │   └── hero-stratosphere.png
        ├── components/
        │   ├── Globe.jsx              # Leaflet: balloons + stations
        │   ├── AltitudeColumn.jsx     # Three.js profile column
        │   ├── FlightScrubber.jsx
        │   ├── StationScrubber.jsx    # Station time / level scrubbing
        │   ├── SoundingChart.jsx
        │   ├── WindBarbs.jsx
        │   ├── ScoreCard.jsx
        │   └── ModelCard.jsx          # Present in repo; not wired into main dashboard tabs
        ├── pages/
        │   ├── LandingPage.jsx
        │   └── DashboardPage.jsx
        ├── styles/
        │   ├── landing.css
        │   └── dashboard.css
        └── utils/
            ├── atmospheric.js
            └── wind.js
```

## Data sources

- **[SondeHub](https://sondehub.org)** — Community radiosonde telemetry; used for the global live map and per-serial paths and analysis.
- **[Synoptic Data](https://synopticdata.com/)** — Mesonet and station metadata, latest obs, and time series; used for map overlays, hybrid profiles, and station-mode dashboards when `SYNOPTIC_TOKEN` is set.
