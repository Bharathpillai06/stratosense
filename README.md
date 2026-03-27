# StratoSense

Real-time atmospheric analysis platform for weather balloon telemetry. Tracks active radiosondes worldwide via SondeHub, runs meteorological calculations on flight data, and visualizes results in an interactive dashboard.

## Features

- **Live Balloon Tracker** — interactive globe map showing active radiosondes worldwide
- **Atmospheric Sounding Chart** — temperature and dewpoint profiles vs altitude
- **Wind Barb Visualization** — standard meteorological wind profile by altitude band
- **Instability Score Card** — CAPE, CIN, lapse rate, tropopause altitude, precipitable water, and storm risk
- **Plain English Forecasts** — human-readable atmospheric summaries generated from the data
- **Flight Timeline Scrubber** — replay a balloon's ascent frame by frame
- **Real-time Updates** — backend polls SondeHub every 30 seconds; frontend refreshes every 2–30 seconds via REST + WebSocket

## Architecture

```text
SondeHub API  →  Flask + SocketIO backend (port 8080)  →  React + Vite frontend (port 5173)
```

| Layer | Technology |
| --- | --- |
| Data source | SondeHub API (global radiosonde network) |
| Backend | Python 3, Flask, Flask-SocketIO |
| Frontend | React 19, Vite 8 |
| Mapping | Leaflet |
| Charts | Chart.js 4 + react-chartjs-2 |

## Requirements

### Backend (Python)

- Python 3.9+
- `flask`
- `flask-socketio`
- `requests`

Install with:

```bash
pip install flask flask-socketio requests
```

### Frontend (Node)

- Node.js 18+
- npm 9+

Dependencies are listed in [frontend/package.json](frontend/package.json). Key packages:

- `react` 19
- `vite` 8
- `chart.js` 4 + `react-chartjs-2`
- `chartjs-plugin-annotation`
- `chartjs-plugin-zoom`
- `leaflet` + `react-leaflet`

## Setup & Running

### 1. Start the backend

```bash
cd src
python data_pipeline.py
```

Server starts on `http://localhost:8080`. On first run it fetches all active balloons from SondeHub and begins a 30-second polling loop in the background.

### 2. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

App opens at `http://localhost:5173`.

## API Endpoints

| Method | Path | Description |
| --- | --- | --- |
| GET | `/balloons` | List all cached balloons with metadata |
| GET | `/balloon/<serial>` | Full telemetry + atmospheric analysis for one balloon |
| GET | `/status` | Server health and balloon count |
| WS | — | SocketIO connection for real-time balloon updates |

## Atmospheric Calculations

The backend ([src/data_pipeline.py](src/data_pipeline.py)) computes the following from raw radiosonde telemetry:

- **Lapse rate** — environmental temperature gradient (K/km)
- **Tropopause detection** — altitude where lapse rate inverts
- **CAPE / CIN** — convective available potential energy and convective inhibition
- **Wind shear profile** — speed and direction at altitude bands
- **Precipitable water** — integrated moisture content estimate
- **Storm risk classification** — low / moderate / high / extreme based on CAPE thresholds

## Project Structure

```text
stratosense/
├── src/
│   ├── data_pipeline.py        # Flask backend + atmospheric analysis
│   └── test_data_pipeline.py   # Backend tests
└── frontend/
    ├── package.json
    ├── vite.config.js
    └── src/
        ├── App.jsx                          # Root component, layout, global scrubber
        ├── components/
        │   ├── Globe.jsx                    # Leaflet balloon map
        │   ├── FlightScrubber.jsx           # Timeline slider
        │   ├── AltitudeColumn.jsx           # Altitude display
        │   ├── SoundingChart.jsx            # Temperature/dewpoint chart
        │   ├── WindBarbs.jsx                # SVG wind barb visualization
        │   └── ScoreCard.jsx                # Instability metrics dashboard
        └── utils/
            ├── atmospheric.js               # Dewpoint (Magnus formula)
            └── wind.js                      # Wind data grouping by altitude band
```

## Data Source

Balloon telemetry is sourced from [SondeHub](https://sondehub.org), a community-driven global radiosonde tracking network. No API key is required for read access.
