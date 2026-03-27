export default function FlightScrubber({ frames, scrubIndex, onChange }) {
  if (!frames || frames.length === 0) return null;

  const max = frames.length - 1;
  const current = frames[scrubIndex] ?? frames[max];
  const first = frames[0];
  const last = frames[max];

  function fmtTime(isoStr) {
    if (!isoStr) return '—';
    try {
      return new Date(isoStr).toLocaleTimeString([], {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      });
    } catch {
      return isoStr;
    }
  }

  function fmtAlt(f) {
    if (!f?.alt) return '';
    return `${(f.alt / 1000).toFixed(1)} km`;
  }

  const pct = max > 0 ? (scrubIndex / max) * 100 : 100;
  const isLive = scrubIndex >= max;

  return (
    <div className="flight-scrubber">
      <div className="scrubber-info-row">
        <span className="scrubber-current-time">{fmtTime(current?.datetime)}</span>
        <span className="scrubber-current-alt">{fmtAlt(current)}</span>
        {current?.temp != null && (
          <span className="scrubber-current-temp">{current.temp.toFixed(1)}°C</span>
        )}
        {isLive && <span className="scrubber-live-badge">LIVE</span>}
      </div>

      <div className="scrubber-track-wrap">
        <span className="scrubber-label">
          Launch
          <br />
          <small>{fmtTime(first?.datetime)}</small>
        </span>

        <div className="scrubber-range-wrap">
          <div
            className="scrubber-fill"
            style={{ width: `${pct}%` }}
          />
          <input
            type="range"
            min={0}
            max={max}
            value={scrubIndex}
            onChange={(e) => onChange(Number(e.target.value))}
            className="scrubber-range"
          />
        </div>

        <span className="scrubber-label live-label">
          Live
          <br />
          <small>{fmtTime(last?.datetime)}</small>
        </span>
      </div>

      <div className="scrubber-alt-bar">
        {frames.map((f, i) => {
          if (!f.alt) return null;
          const x = (i / max) * 100;
          const h = Math.min(100, (f.alt / 35000) * 100);
          return (
            <div
              key={i}
              className="scrubber-alt-tick"
              style={{
                left: `${x}%`,
                height: `${h}%`,
                opacity: i <= scrubIndex ? 0.9 : 0.2,
              }}
            />
          );
        })}
      </div>
    </div>
  );
}
