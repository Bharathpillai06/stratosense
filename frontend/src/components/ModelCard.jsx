import { useEffect, useRef, useState } from 'react';

const POLL_MS = 5000;

const KEY_ALTITUDES = [300, 500, 1000, 3000, 5000];

function confPct(confidence) {
  if (confidence === 'high') return 90;
  if (confidence === 'medium') return 60;
  return 30;
}

export default function ModelCard({ serial }) {
  const [profile, setProfile] = useState(null);
  const [status, setStatus] = useState(null);
  const [da, setDa] = useState(null);
  const [loading, setLoading] = useState(false);
  const [unavailable, setUnavailable] = useState(false);
  const pollRef = useRef(null);

  useEffect(() => {
    let cancelled = false;

    async function fetchAll() {
      try {
        const [pRes, sRes, dRes] = await Promise.all([
          fetch('/atmosphere/profile'),
          fetch('/atmosphere/status'),
          fetch('/atmosphere/density_altitude'),
        ]);
        if (!pRes.ok || !sRes.ok || !dRes.ok) {
          if (!cancelled) setUnavailable(true);
          return;
        }
        const [pData, sData, dData] = await Promise.all([
          pRes.json(), sRes.json(), dRes.json(),
        ]);
        if (!cancelled) {
          setProfile(pData);
          setStatus(sData);
          setDa(dData);
          setUnavailable(false);
        }
      } catch {
        if (!cancelled) setUnavailable(true);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    setLoading(true);
    setUnavailable(false);

    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }

    fetchAll().then(() => {
      if (!cancelled) {
        pollRef.current = setInterval(() => {
          if (!cancelled) fetchAll();
        }, POLL_MS);
      }
    });

    return () => {
      cancelled = true;
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [serial]);

  if (unavailable) return null;
  if (loading && !profile) {
    return (
      <div className="model-card-container">
        <div className="chart-header">
          <h2>Atmospheric Model</h2>
        </div>
        <div className="chart-overlay">
          <div className="spinner" />
          <p>Loading atmospheric model...</p>
        </div>
      </div>
    );
  }
  if (!status || !da) return null;

  const isAssim = status.mode === 'assimilated';
  const badgeColor = isAssim ? '#5dcaa5' : '#ef9f27';
  const badgeLabel = isAssim ? 'Assimilated' : 'Interpolated';
  const lrObserved = status.lapse_rate_source === 'observed';
  const lrColor = lrObserved ? '#5dcaa5' : '#ef9f27';
  const lrLabel = lrObserved ? 'Observed' : 'Standard';
  const conf = confPct(status.confidence);

  const keyLevels = profile?.profile
    ? KEY_ALTITUDES.map(
        (a) => profile.profile.find((l) => l.altitude_m >= a) ?? null
      ).filter(Boolean)
    : [];

  return (
    <div className="model-card-container">
      <div className="chart-header">
        <h2>Atmospheric Model</h2>
        <span className="mode-badge" style={{ background: badgeColor, color: '#fff', padding: '3px 10px', borderRadius: 12, fontSize: 12 }}>
          {badgeLabel}
        </span>
      </div>

      {/* Density Altitude hero */}
      <div style={{ textAlign: 'center', margin: '14px 0 10px' }}>
        <div style={{ color: '#888', fontSize: 11, textTransform: 'uppercase', letterSpacing: 1 }}>Density Altitude</div>
        <div style={{ fontSize: 40, fontWeight: 700 }}>{da.density_altitude_ft?.toFixed(0) ?? '—'} ft</div>
        <div style={{ color: '#888', fontSize: 13 }}>{da.density_altitude_m?.toFixed(0) ?? '—'} m</div>
      </div>

      {/* Lapse Rate + Balloon Data */}
      <div style={{ display: 'flex', gap: 10, margin: '10px 0' }}>
        <div className="model-stat-box">
          <div className="model-stat-label">Lapse Rate</div>
          <div className="model-stat-value">{status.lapse_rate_c_per_km}°C/km</div>
          <span className="model-stat-badge" style={{ background: lrColor }}>{lrLabel}</span>
        </div>
        <div className="model-stat-box">
          <div className="model-stat-label">Balloon Data</div>
          <div className="model-stat-value">
            {status.balloon_age_hours != null
              ? `${status.balloon_age_hours.toFixed(1)} hrs ago`
              : 'None'}
          </div>
        </div>
      </div>

      {/* Confidence bar */}
      <div className="model-conf-track">
        <div className="model-conf-fill" style={{ width: `${conf}%`, background: badgeColor }} />
      </div>
      <div style={{ color: '#888', fontSize: 11, marginBottom: 10 }}>{conf}% confidence</div>

      {/* Key altitudes table */}
      {keyLevels.length > 0 && (
        <table className="model-table">
          <thead>
            <tr>
              <th>Alt</th><th>Temp</th><th>Press</th><th>RH</th><th>Wind</th><th>Assim</th>
            </tr>
          </thead>
          <tbody>
            {keyLevels.map((l) => (
              <tr key={l.altitude_m}>
                <td>{(l.altitude_m / 1000).toFixed(1)} km</td>
                <td>{l.temp_c.toFixed(1)}°C</td>
                <td>{l.pressure_hpa.toFixed(0)} hPa</td>
                <td>{l.humidity_pct.toFixed(0)}%</td>
                <td>{l.wind.speed_ms} m/s</td>
                <td>{l.source === 'assimilated' ? '✓' : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
