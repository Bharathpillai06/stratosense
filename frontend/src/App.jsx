import { useState, useEffect, useCallback } from 'react';
import Globe from './components/Globe';
import AltitudeColumn from './components/AltitudeColumn';
import FlightScrubber from './components/FlightScrubber';
import SoundingChart from './components/SoundingChart';
import WindBarbs from './components/WindBarbs';
import ScoreCard from './components/ScoreCard';
import './App.css';

function formatTimeOfDay(seconds) {
  const h = Math.floor(seconds / 3600) % 24;
  const m = Math.floor((seconds % 3600) / 60);
  const ampm = h >= 12 ? 'PM' : 'AM';
  const h12 = h % 12 || 12;
  return `${h12}:${String(m).padStart(2, '0')} ${ampm}`;
}

function nowSeconds() {
  const d = new Date();
  return d.getHours() * 3600 + d.getMinutes() * 60 + d.getSeconds();
}

export default function App() {
  const [serialInput, setSerialInput] = useState('');
  const [activeSerial, setActiveSerial] = useState(null);
  const [serverStatus, setServerStatus] = useState(null);

  // Global time-of-day slider (0–86400 s)
  const [timeOfDay, setTimeOfDay] = useState(nowSeconds);

  // Per-balloon flight scrubber
  const [flightFrames, setFlightFrames] = useState(null);
  const [scrubIndex, setScrubIndex] = useState(0);
  const [analysis, setAnalysis] = useState(null);

  // Status check
  useEffect(() => {
    fetch('/status')
      .then((r) => r.json())
      .then(setServerStatus)
      .catch(() => setServerStatus({ status: 'offline' }));
  }, []);

  // Listen for balloonSelected DOM events from the Globe
  useEffect(() => {
    function onBalloonSelected(e) {
      const serial = e.detail?.serial;
      if (serial) {
        setSerialInput(serial);
        setActiveSerial(serial);
      }
    }
    document.addEventListener('balloonSelected', onBalloonSelected);
    return () => document.removeEventListener('balloonSelected', onBalloonSelected);
  }, []);

  // Fetch flight path + analysis whenever active balloon changes
  const loadFlightData = useCallback(async (serial) => {
    setFlightFrames(null);
    setAnalysis(null);
    setScrubIndex(0);
    if (!serial) return;
    try {
      const [pathRes, analysisRes] = await Promise.all([
        fetch(`/balloon/${serial}`),
        fetch(`/balloon/${serial}/analysis`),
      ]);
      if (pathRes.ok) {
        const d = await pathRes.json();
        const frames = (d.path || []).filter(
          (f) => f.lat != null && f.lon != null
        );
        setFlightFrames(frames);
        setScrubIndex(Math.max(0, frames.length - 1));
      }
      if (analysisRes.ok) {
        setAnalysis(await analysisRes.json());
      }
    } catch {
      // non-critical — charts handle their own errors
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function run() {
      if (!cancelled) await loadFlightData(activeSerial);
    }
    run();
    return () => { cancelled = true; };
  }, [activeSerial, loadFlightData]);

  function handleLoad(e) {
    e.preventDefault();
    const trimmed = serialInput.trim();
    if (trimmed) setActiveSerial(trimmed);
  }

  const online = serverStatus?.status === 'running';
  const scrubFrame = flightFrames?.[scrubIndex] ?? null;

  return (
    <div className="app">
      <header className="app-header">
        <div className="brand">
          <h1>StratoSense</h1>
          <span className="subtitle">Atmospheric Analysis</span>
        </div>

        {/* Global time-of-day slider */}
        <div className="time-slider-wrap">
          <span className="time-label">12 AM</span>
          <div className="time-track">
            <div
              className="time-fill"
              style={{ width: `${(timeOfDay / 86400) * 100}%` }}
            />
            <input
              type="range"
              min={0}
              max={86400}
              value={timeOfDay}
              onChange={(e) => setTimeOfDay(Number(e.target.value))}
              className="time-range"
            />
          </div>
          <span className="time-label">12 AM+1</span>
          <span className="time-current">{formatTimeOfDay(timeOfDay)}</span>
          <button
            className="time-now-btn"
            onClick={() => setTimeOfDay(nowSeconds())}
          >
            NOW
          </button>
        </div>

        <div className={`status-dot ${online ? 'online' : 'offline'}`}>
          {online
            ? `Pipeline online — ${serverStatus.active_balloons} active`
            : 'Pipeline offline'}
        </div>
      </header>

      <div className="app-body">
        {/* ── LEFT: globe + flight scrubber ── */}
        <div className="left-panel">
          <Globe selectedSerial={activeSerial} scrubFrame={scrubFrame} />

          <FlightScrubber
            frames={flightFrames}
            scrubIndex={scrubIndex}
            onChange={setScrubIndex}
          />
        </div>

        {/* ── RIGHT: controls + altitude column + charts ── */}
        <div className="right-panel">
          <div className="controls">
            <form onSubmit={handleLoad} className="serial-form">
              <input
                type="text"
                value={serialInput}
                onChange={(e) => setSerialInput(e.target.value)}
                placeholder="Serial (e.g. T1234567) — or click globe"
                className="serial-input"
              />
              <button
                type="submit"
                className="btn btn-primary"
                disabled={!serialInput.trim()}
              >
                Load
              </button>
            </form>
            {activeSerial && (
              <span className="active-serial-display">
                <strong>{activeSerial}</strong>
              </span>
            )}
          </div>

          <div className="chart-area">
            <AltitudeColumn
              frames={flightFrames}
              scrubIndex={scrubIndex}
              analysis={analysis}
            />
            <SoundingChart serial={activeSerial} />
            <WindBarbs serial={activeSerial} />
            <ScoreCard serial={activeSerial} />
          </div>
        </div>
      </div>
    </div>
  );
}
