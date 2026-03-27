import { useEffect, useRef, useMemo } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

// ── Color helpers ────────────────────────────────────────────────────────────

const TEMP_STOPS = [
  { t: -70, r: 10,  g: 10,  b: 180 },
  { t: -50, r: 0,   g: 80,  b: 255 },
  { t: -30, r: 0,   g: 180, b: 240 },
  { t: -10, r: 0,   g: 210, b: 160 },
  { t:   5, r: 80,  g: 230, b: 50  },
  { t:  15, r: 220, g: 230, b: 0   },
  { t:  25, r: 255, g: 130, b: 0   },
  { t:  40, r: 230, g: 20,  b: 20  },
];

function tempToRGB01(temp) {
  if (temp == null) return [0.3, 0.3, 0.3];
  if (temp <= TEMP_STOPS[0].t) {
    const s = TEMP_STOPS[0];
    return [s.r / 255, s.g / 255, s.b / 255];
  }
  if (temp >= TEMP_STOPS[TEMP_STOPS.length - 1].t) {
    const s = TEMP_STOPS[TEMP_STOPS.length - 1];
    return [s.r / 255, s.g / 255, s.b / 255];
  }
  for (let i = 0; i < TEMP_STOPS.length - 1; i++) {
    if (temp >= TEMP_STOPS[i].t && temp <= TEMP_STOPS[i + 1].t) {
      const f = (temp - TEMP_STOPS[i].t) / (TEMP_STOPS[i + 1].t - TEMP_STOPS[i].t);
      return [
        (TEMP_STOPS[i].r + f * (TEMP_STOPS[i + 1].r - TEMP_STOPS[i].r)) / 255,
        (TEMP_STOPS[i].g + f * (TEMP_STOPS[i + 1].g - TEMP_STOPS[i].g)) / 255,
        (TEMP_STOPS[i].b + f * (TEMP_STOPS[i + 1].b - TEMP_STOPS[i].b)) / 255,
      ];
    }
  }
  return [0.3, 0.3, 0.3];
}

function tempToCss(temp) {
  const [r, g, b] = tempToRGB01(temp);
  return `rgb(${Math.round(r * 255)},${Math.round(g * 255)},${Math.round(b * 255)})`;
}

// ── Axis builder ─────────────────────────────────────────────────────────────

function makeAxisLine(from, to, color) {
  const geo = new THREE.BufferGeometry().setFromPoints([
    new THREE.Vector3(...from),
    new THREE.Vector3(...to),
  ]);
  const mat = new THREE.LineBasicMaterial({ color, opacity: 0.5, transparent: true });
  return new THREE.Line(geo, mat);
}

function makeGridLine(from, to) {
  const geo = new THREE.BufferGeometry().setFromPoints([
    new THREE.Vector3(...from),
    new THREE.Vector3(...to),
  ]);
  const mat = new THREE.LineBasicMaterial({ color: 0x1e3a5f, opacity: 0.6, transparent: true });
  return new THREE.Line(geo, mat);
}

// ── Component ────────────────────────────────────────────────────────────────

export default function AltitudeColumn({ frames, scrubIndex, analysis }) {
  const mountRef = useRef(null);
  const threeRef = useRef(null); // { renderer, scene, camera, controls, animId }
  const soundingGroupRef = useRef(null);

  const validFrames = useMemo(
    () =>
      (frames || [])
        .filter((f) => f.alt != null && f.temp != null)
        .sort((a, b) => a.alt - b.alt),
    [frames]
  );

  const scrubFrame = frames && scrubIndex != null ? frames[scrubIndex] : null;

  // ── One-time Three.js scene setup ──────────────────────────────────────────
  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;

    const W = mount.clientWidth || 400;
    const H = 360;

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(W, H);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setClearColor(0x0d1b2e);
    mount.appendChild(renderer.domElement);

    const scene = new THREE.Scene();

    const camera = new THREE.PerspectiveCamera(42, W / H, 0.01, 100);
    camera.position.set(2.2, 1.4, 2.2);
    camera.lookAt(0.5, 0.5, 0.5);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.set(0.5, 0.5, 0.5);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.update();

    // Box axes
    scene.add(makeAxisLine([0, 0, 0], [1, 0, 0], 0x4488cc)); // temp → X (blue)
    scene.add(makeAxisLine([0, 0, 0], [0, 1, 0], 0x44cc88)); // alt → Y (green)
    scene.add(makeAxisLine([0, 0, 0], [0, 0, 1], 0xcc8844)); // humid → Z (orange)

    // Floor grid lines
    for (let i = 0; i <= 4; i++) {
      const v = i / 4;
      scene.add(makeGridLine([v, 0, 0], [v, 0, 1]));
      scene.add(makeGridLine([0, 0, v], [1, 0, v]));
    }

    const group = new THREE.Group();
    scene.add(group);
    soundingGroupRef.current = group;

    let animId;
    const animate = () => {
      animId = requestAnimationFrame(animate);
      controls.update();
      renderer.render(scene, camera);
    };
    animate();

    threeRef.current = { renderer, scene, camera, controls, animId };

    const handleResize = () => {
      const w = mount.clientWidth || 400;
      renderer.setSize(w, H);
      camera.aspect = w / H;
      camera.updateProjectionMatrix();
    };
    window.addEventListener('resize', handleResize);

    return () => {
      cancelAnimationFrame(animId);
      window.removeEventListener('resize', handleResize);
      controls.dispose();
      renderer.dispose();
      if (mount.contains(renderer.domElement)) mount.removeChild(renderer.domElement);
    };
  }, []);

  // ── Update sounding geometry when data changes ─────────────────────────────
  useEffect(() => {
    const group = soundingGroupRef.current;
    if (!group) return;

    // Clear previous objects
    while (group.children.length) {
      const obj = group.children[0];
      obj.geometry?.dispose();
      obj.material?.dispose();
      group.remove(obj);
    }

    if (validFrames.length < 2) return;

    const temps = validFrames.map((f) => f.temp);
    const alts = validFrames.map((f) => f.alt);

    const tempMin = Math.min(...temps);
    const tempMax = Math.max(...temps);
    const altMax  = Math.max(...alts);
    const tRange  = tempMax - tempMin || 1;

    const norm = (f) => ({
      x: (f.temp - tempMin) / tRange,
      y: f.alt / altMax,
      z: (f.humidity ?? 0) / 100,
    });

    // ── Colored line segments ──────────────────────────────────
    const positions = [];
    const colors    = [];

    for (let i = 0; i < validFrames.length - 1; i++) {
      const a = norm(validFrames[i]);
      const b = norm(validFrames[i + 1]);
      positions.push(a.x, a.y, a.z, b.x, b.y, b.z);
      const [ar, ag, ab] = tempToRGB01(validFrames[i].temp);
      const [br, bg, bb] = tempToRGB01(validFrames[i + 1].temp);
      colors.push(ar, ag, ab, br, bg, bb);
    }

    const lineGeo = new THREE.BufferGeometry();
    lineGeo.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    lineGeo.setAttribute('color',    new THREE.Float32BufferAttribute(colors, 3));
    const lineMat = new THREE.LineBasicMaterial({ vertexColors: true, linewidth: 2 });
    group.add(new THREE.LineSegments(lineGeo, lineMat));

    // ── Small spheres along the path ──────────────────────────
    const sphereGeo = new THREE.SphereGeometry(0.012, 8, 8);
    validFrames.forEach((f) => {
      const p = norm(f);
      const [r, g, b] = tempToRGB01(f.temp);
      const mat = new THREE.MeshBasicMaterial({ color: new THREE.Color(r, g, b) });
      const mesh = new THREE.Mesh(sphereGeo, mat);
      mesh.position.set(p.x, p.y, p.z);
      group.add(mesh);
    });

    // ── Tropopause plane ──────────────────────────────────────
    const tropo = analysis?.tropopause_alt_m;
    if (tropo && tropo <= altMax) {
      const ty = tropo / altMax;
      const planeGeo = new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(0, ty, 0), new THREE.Vector3(1, ty, 0),
        new THREE.Vector3(1, ty, 1), new THREE.Vector3(0, ty, 1),
        new THREE.Vector3(0, ty, 0),
      ]);
      const planeMat = new THREE.LineBasicMaterial({
        color: 0xcc88ff, opacity: 0.6, transparent: true,
      });
      group.add(new THREE.Line(planeGeo, planeMat));
    }

    // ── Scrub marker ──────────────────────────────────────────
    if (scrubFrame?.temp != null && scrubFrame?.alt != null) {
      const p = norm(scrubFrame);
      const markerGeo = new THREE.SphereGeometry(0.03, 16, 16);
      const markerMat = new THREE.MeshBasicMaterial({ color: 0xffffff });
      const marker = new THREE.Mesh(markerGeo, markerMat);
      marker.position.set(p.x, p.y, p.z);
      group.add(marker);

      // Vertical drop line
      const dropGeo = new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(p.x, 0, p.z),
        new THREE.Vector3(p.x, p.y, p.z),
      ]);
      const dropMat = new THREE.LineBasicMaterial({
        color: 0xffffff, opacity: 0.35, transparent: true,
      });
      group.add(new THREE.Line(dropGeo, dropMat));
    }

    // Store normalization for label rendering
    group.userData = { tempMin, tempMax, altMax };
  }, [validFrames, scrubFrame, analysis]);

  // ── Derived display values ─────────────────────────────────────────────────
  const badgeColor   = scrubFrame?.temp != null ? tempToCss(scrubFrame.temp) : '#334455';
  const currentTemp  = scrubFrame?.temp;
  const currentHumid = scrubFrame?.humidity;
  const currentAlt   = scrubFrame?.alt;
  const currentVelV  = scrubFrame?.vel_v;

  // Axis label positions (approximate screen corners, shown as overlays)
  const { tempMin, tempMax, altMax } = soundingGroupRef.current?.userData ?? {};

  return (
    <div className="altitude-column-wrap">
      <div className="altitude-col-header">
        <span>Altitude Profile 3D</span>
        {currentTemp != null && (
          <span className="alt-col-badge" style={{ background: badgeColor }}>
            {currentTemp.toFixed(1)}°C
          </span>
        )}
      </div>

      {/* 3D canvas mount + axis labels overlay */}
      <div className="altitude-3d-scene-wrap">
        <div ref={mountRef} className="altitude-3d-mount" />

        {/* Axis legend overlay */}
        <div className="altitude-3d-legend">
          <span className="axis-label axis-x">
            ← Temp {tempMin != null ? `(${Math.round(tempMin)}…${Math.round(tempMax)}°C)` : '(°C)'}
          </span>
          <span className="axis-label axis-y">
            ↑ Alt {altMax != null ? `(0…${(altMax / 1000).toFixed(0)} km)` : '(km)'}
          </span>
          <span className="axis-label axis-z">
            ↗ Humid (0…100%)
          </span>
          {analysis?.tropopause_alt_m && (
            <span className="axis-label axis-tropo">
              ━ Tropopause {(analysis.tropopause_alt_m / 1000).toFixed(1)} km
            </span>
          )}
        </div>

        {validFrames.length === 0 && (
          <div className="altitude-col-empty altitude-3d-empty">
            <p>Click a balloon to view its altitude profile</p>
          </div>
        )}
      </div>

      {scrubFrame && (
        <div className="altitude-readout-3d">
          <div className="readout-row">
            <span className="readout-key">Alt</span>
            <span className="readout-val">
              {currentAlt != null ? `${(currentAlt / 1000).toFixed(1)} km` : '—'}
            </span>
          </div>
          <div className="readout-row">
            <span className="readout-key">Temp</span>
            <span className="readout-val" style={{ color: badgeColor }}>
              {currentTemp != null ? `${currentTemp.toFixed(1)} °C` : '—'}
            </span>
          </div>
          <div className="readout-row">
            <span className="readout-key">Humid</span>
            <span className="readout-val">
              {currentHumid != null ? `${Math.round(currentHumid)} %` : '—'}
            </span>
          </div>
          <div className="readout-row">
            <span className="readout-key">Asc</span>
            <span className="readout-val">
              {currentVelV != null ? `${currentVelV.toFixed(1)} m/s` : '—'}
            </span>
          </div>
          {analysis?.cape != null && (
            <div className="readout-row cape-row">
              <span className="readout-key">CAPE</span>
              <span className="readout-val">{Math.round(analysis.cape)} J/kg</span>
            </div>
          )}
          {analysis?.storm_risk && (
            <div className="readout-risk">{analysis.storm_risk}</div>
          )}
        </div>
      )}
    </div>
  );
}
