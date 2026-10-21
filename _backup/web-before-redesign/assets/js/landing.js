// REVIVE landing page.
//  * hero: a procedural building assembles floor by floor under a tower crane at night, then a scan
//    plane sweeps up and recolours it by delay risk, then recovery activities pulse pink (Three.js)
//  * the HUD numbers follow that animation (labelled illustrative)
//  * real figures come from /api/public/overview (cross-validated model card), never hard-coded
//  * tabs, scroll reveals and the pinned pipeline use GSAP + ScrollTrigger (vendored, no CDN)
//  * sign in / create workspace talk to /api/auth/*
import * as THREE from 'three';

document.documentElement.classList.add('js');
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const REDUCED = matchMedia('(prefers-reduced-motion: reduce)').matches;
const HDR = { 'Content-Type': 'application/json', 'X-Revive-Request': '1' };
const ready = new Promise(res => (document.readyState === 'complete' ? res() : addEventListener('load', res)));

// =================================================================== 3D night site
function nightSite() {
  const canvas = $('#scene');
  let renderer;
  try { renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: 'high-performance' }); }
  catch { canvas.hidden = true; return null; }
  renderer.setPixelRatio(Math.min(devicePixelRatio, 1.75));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x040B12);
  scene.fog = new THREE.Fog(0x040B12, 55, 140);
  const camera = new THREE.PerspectiveCamera(36, 1, 0.1, 500);
  const target = new THREE.Vector3(-20, 12, 0);

  scene.add(new THREE.HemisphereLight(0x7FD3F7, 0x040B12, 0.55));
  const key = new THREE.DirectionalLight(0xFFD9A0, 1.1); key.position.set(30, 40, 20); scene.add(key);
  const rim = new THREE.DirectionalLight(0x7FD3F7, 0.6); rim.position.set(-30, 20, -30); scene.add(rim);

  // ground: blueprint grid and a floodlit pool under the building
  const grid = new THREE.GridHelper(240, 120, 0x7FD3F7, 0x0F2A3D);
  grid.material.transparent = true; grid.material.opacity = 0.28; scene.add(grid);
  const glowTex = (() => {
    const c = document.createElement('canvas'); c.width = c.height = 256;
    const g = c.getContext('2d'), r = g.createRadialGradient(128, 128, 0, 128, 128, 128);
    r.addColorStop(0, 'rgba(255,181,71,0.35)'); r.addColorStop(0.5, 'rgba(255,181,71,0.08)'); r.addColorStop(1, 'rgba(255,181,71,0)');
    g.fillStyle = r; g.fillRect(0, 0, 256, 256);
    return new THREE.CanvasTexture(c);
  })();
  const pool = new THREE.Mesh(new THREE.PlaneGeometry(60, 60), new THREE.MeshBasicMaterial({ map: glowTex, transparent: true, depthWrite: false }));
  pool.rotation.x = -Math.PI / 2; pool.position.y = 0.02; scene.add(pool);

  // building: 4 x 3 bays, 6 storeys; columns and beams are instanced so each can be recoloured
  const BX = 4, BZ = 3, SP = 6, SH = 3.6, NS = 6, ox = -(BX * SP) / 2, oz = -(BZ * SP) / 2;
  const mat = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.65, metalness: 0.05 });
  const cols = new THREE.InstancedMesh(new THREE.BoxGeometry(0.55, SH, 0.55), mat, (BX + 1) * (BZ + 1) * NS);
  const beamsX = new THREE.InstancedMesh(new THREE.BoxGeometry(SP, 0.5, 0.35), mat, BX * (BZ + 1) * NS);
  const beamsZ = new THREE.InstancedMesh(new THREE.BoxGeometry(0.35, 0.5, SP), mat, (BX + 1) * BZ * NS);
  [cols, beamsX, beamsZ].forEach(m => { m.instanceMatrix.setUsage(THREE.DynamicDrawUsage); scene.add(m); });
  const items = [];   // {mesh, i, storey, base: Matrix parts, kind}
  const add = (mesh, i, s, x, y, z, kind) => items.push({ mesh, i, s, x, y, z, kind });
  let ci = 0, bxi = 0, bzi = 0;
  for (let s = 0; s < NS; s++) {
    const y0 = s * SH;
    for (let i = 0; i <= BX; i++) for (let k = 0; k <= BZ; k++) add(cols, ci++, s, ox + i * SP, y0 + SH / 2, oz + k * SP, 'col');
    for (let i = 0; i < BX; i++) for (let k = 0; k <= BZ; k++) add(beamsX, bxi++, s, ox + (i + 0.5) * SP, y0 + SH - 0.25, oz + k * SP, 'beam');
    for (let i = 0; i <= BX; i++) for (let k = 0; k < BZ; k++) add(beamsZ, bzi++, s, ox + i * SP, y0 + SH - 0.25, oz + (k + 0.5) * SP, 'beam');
  }
  const slabs = [];
  const slabGeo = new THREE.BoxGeometry(BX * SP + 0.8, 0.3, BZ * SP + 0.8), slabEdges = new THREE.EdgesGeometry(slabGeo);
  for (let s = 0; s < NS; s++) {
    const m = new THREE.Mesh(slabGeo, new THREE.MeshStandardMaterial({ color: 0xB8C7CF, roughness: 0.8, transparent: true, opacity: 0.9 }));
    m.position.set(0, (s + 1) * SH, 0);
    const e = new THREE.LineSegments(slabEdges, new THREE.LineBasicMaterial({ color: 0x7FD3F7, transparent: true, opacity: 0.7 }));
    m.add(e); scene.add(m); slabs.push(m);
  }
  // risk colour of each storey after the scan (lower floors done, upper floors carry the delay)
  const C = { built: new THREE.Color(0xB8C7CF), done: new THREE.Color(0x8C9AA3), go: new THREE.Color(0x3DD68C), watch: new THREE.Color(0xF2C94C),
    risk: new THREE.Color(0xFF8A3D), crit: new THREE.Color(0xFF4D5E), mark: new THREE.Color(0xFF4FA3), active: new THREE.Color(0xFFB547) };
  const riskOf = [C.done, C.done, C.go, C.watch, C.risk, C.crit];
  const crashed = new Set([4, 5]);

  // scan plane
  const scan = new THREE.Mesh(new THREE.PlaneGeometry(BX * SP + 8, BZ * SP + 8), new THREE.MeshBasicMaterial({ color: 0x7FD3F7, transparent: true, opacity: 0.0, side: THREE.DoubleSide, depthWrite: false }));
  scan.rotation.x = -Math.PI / 2; scene.add(scan);
  const scanEdge = new THREE.LineSegments(new THREE.EdgesGeometry(scan.geometry), new THREE.LineBasicMaterial({ color: 0x7FD3F7, transparent: true, opacity: 0 }));
  scan.add(scanEdge);

  // tower crane in linework
  const crane = new THREE.Group(); crane.position.set(-22, 0, -14); scene.add(crane);
  const line = (geo, c = 0x7FD3F7, o = 0.85) => new THREE.LineSegments(new THREE.EdgesGeometry(geo), new THREE.LineBasicMaterial({ color: c, transparent: true, opacity: o }));
  const H = 34;
  for (let y = 0; y < H; y += 2) { const seg = line(new THREE.BoxGeometry(1.2, 2, 1.2)); seg.position.y = y + 1; crane.add(seg); }
  const slew = new THREE.Group(); slew.position.y = H; crane.add(slew);
  const jib = line(new THREE.BoxGeometry(32, 1, 1)); jib.position.x = 15; slew.add(jib);
  const cjib = line(new THREE.BoxGeometry(10, 1, 1)); cjib.position.x = -6; slew.add(cjib);
  const cab = new THREE.Mesh(new THREE.BoxGeometry(1.6, 1.4, 1.6), new THREE.MeshBasicMaterial({ color: 0xFFB547 })); cab.position.set(0, -1, 0.4); slew.add(cab);
  const tip = new THREE.Mesh(new THREE.SphereGeometry(0.25, 8, 8), new THREE.MeshBasicMaterial({ color: 0xFF4D5E })); tip.position.set(31, 0.8, 0); slew.add(tip);
  const trolley = new THREE.Group(); slew.add(trolley);
  const cableGeo = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3(0, -10, 0)]);
  const cable = new THREE.Line(cableGeo, new THREE.LineBasicMaterial({ color: 0xA3BCC8, transparent: true, opacity: 0.7 })); trolley.add(cable);
  const hook = new THREE.Mesh(new THREE.BoxGeometry(0.7, 0.7, 0.7), new THREE.MeshBasicMaterial({ color: 0xFFB547 })); trolley.add(hook);
  const flood = new THREE.SpotLight(0xFFB547, 220, 90, 0.5, 0.6, 1.6); flood.position.set(-22, H + 2, -14); flood.target.position.set(0, 6, 0);
  scene.add(flood, flood.target);

  // stars of distant site lights
  const pts = new Float32Array(600 * 3);
  for (let i = 0; i < 600; i++) { const a = Math.random() * Math.PI * 2, r = 70 + Math.random() * 60; pts[i * 3] = Math.cos(a) * r; pts[i * 3 + 1] = Math.random() * 2; pts[i * 3 + 2] = Math.sin(a) * r; }
  const sg = new THREE.BufferGeometry(); sg.setAttribute('position', new THREE.BufferAttribute(pts, 3));
  scene.add(new THREE.Points(sg, new THREE.PointsMaterial({ color: 0xFFB547, size: 0.35, transparent: true, opacity: 0.6 })));

  const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), v = new THREE.Vector3(), sc = new THREE.Vector3(), col = new THREE.Color();
  const PERIOD = 17, ease = t => 1 - Math.pow(1 - Math.min(1, Math.max(0, t)), 3);
  const hud = { at: $('[data-hud=at]'), es: $('[data-hud=es]'), spi: $('[data-hud=spi]'), dl: $('[data-hud=dl]'), bar: $('#hud-scan'), phase: $('#hud-phase') };
  let lastPhase = '';

  function frame(t) {
    const u = t % PERIOD;
    const build = u / 7, scanP = (u - 7.2) / 3.6, recP = (u - 11) / 3, fade = (u - 15.6) / 1.4;
    items.forEach(it => {
      const k = ease((build * NS - it.s) * (it.kind === 'col' ? 1.6 : 1.25) - (it.kind === 'beam' ? 0.35 : 0));
      const vis = fade > 0 ? 1 - ease(fade) : 1;
      const g = k * vis;
      if (it.kind === 'col') { sc.set(1, Math.max(0.001, g), 1); v.set(it.x, it.s * SH + (SH * g) / 2, it.z); }
      else { sc.set(Math.max(0.001, g), 1, Math.max(0.001, g)); v.set(it.x, it.y + (1 - g) * 2, it.z); }
      m4.compose(v, q, sc); it.mesh.setMatrixAt(it.i, m4);
      const scanned = scanP > 0 && scanP * NS * 1.05 > it.s;
      if (scanned) col.copy(riskOf[it.s]); else col.copy(k < 1 ? C.active : C.built);
      if (recP > 0 && crashed.has(it.s)) col.lerp(C.mark, 0.55 + 0.45 * Math.sin(t * 6));
      it.mesh.setColorAt(it.i, col);
    });
    [cols, beamsX, beamsZ].forEach(m => { m.instanceMatrix.needsUpdate = true; if (m.instanceColor) m.instanceColor.needsUpdate = true; });
    slabs.forEach((s, i) => {
      const k = ease((build * NS - i) * 1.25 - 0.7), vis = fade > 0 ? 1 - ease(fade) : 1;
      s.visible = k > 0.01 && vis > 0.01;
      s.position.y = (i + 1) * SH + (1 - k) * 3;
      s.material.opacity = 0.85 * k * vis; s.children[0].material.opacity = 0.75 * k * vis;
      const scanned = scanP > 0 && scanP * NS * 1.05 > i;
      s.material.color.copy(scanned ? riskOf[i] : C.built);
      if (recP > 0 && crashed.has(i)) s.material.color.lerp(C.mark, 0.4 + 0.3 * Math.sin(t * 6));
    });
    const sp = Math.min(1, Math.max(0, scanP));
    scan.position.y = sp * NS * SH + 0.4;
    scan.material.opacity = scanP > 0 && scanP < 1.05 ? 0.12 : 0;
    scanEdge.material.opacity = scanP > 0 && scanP < 1.05 ? 0.9 : 0;
    // crane works while the building rises
    slew.rotation.y = -0.6 + Math.sin(t * 0.22) * 0.55;
    const tr = 10 + (Math.sin(t * 0.5) * 0.5 + 0.5) * 18; trolley.position.x = tr;
    const drop = 6 + (Math.sin(t * 0.8) * 0.5 + 0.5) * 14;
    hook.position.y = -drop; cableGeo.attributes.position.setY(1, -drop); cableGeo.attributes.position.needsUpdate = true;
    // illustrative readout, tied to the scene
    const atD = Math.round(150 * Math.min(1, u / 7)), esD = Math.round(131 * Math.min(1, u / 7));
    hud.at.textContent = `day ${atD}`; hud.es.textContent = `day ${esD}`;
    hud.spi.textContent = atD ? (esD / atD).toFixed(2) : '1.00';
    hud.dl.textContent = `+${atD - esD} d`;
    hud.bar.style.width = `${Math.min(100, (u / 15.5) * 100)}%`;
    const phase = u < 7 ? 'Assembling the baseline' : u < 11 ? 'Scanning progress against plan' : u < 15.5 ? 'Optimising the recovery (pink)' : 'Next status date';
    if (phase !== lastPhase) { hud.phase.textContent = phase; lastPhase = phase; }
  }

  let px = 0, py = 0, tx = 0, ty = 0;
  addEventListener('pointermove', e => { tx = (e.clientX / innerWidth - 0.5); ty = (e.clientY / innerHeight - 0.5); }, { passive: true });
  function resize() {
    const w = canvas.clientWidth || innerWidth, h = canvas.clientHeight || innerHeight;
    renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix();
    target.x = w < 900 ? 0 : -20;
  }
  new ResizeObserver(resize).observe(canvas); resize();
  let visible = true, t0 = performance.now(), raf = 0;
  new IntersectionObserver(([e]) => { visible = e.isIntersecting; if (visible && !raf && !REDUCED) loop(); }).observe(canvas);
  function place(t) {
    px += (tx - px) * 0.04; py += (ty - py) * 0.04;
    const a = 0.75 + t * 0.035 + px * 0.5;
    camera.position.set(Math.cos(a) * 84, 30 + py * -8, Math.sin(a) * 84);
    camera.lookAt(target);
  }
  function loop() {
    raf = 0;
    if (!visible || document.hidden) return;
    const t = (performance.now() - t0) / 1000;
    frame(t); place(t); renderer.render(scene, camera);
    raf = requestAnimationFrame(loop);
  }
  document.addEventListener('visibilitychange', () => { if (!document.hidden && visible && !raf && !REDUCED) loop(); });
  if (REDUCED) { frame(12.5); place(0); renderer.render(scene, camera); } else loop();
  return true;
}

// =================================================================== real numbers (model card)
async function overview() {
  try {
    const d = await (await fetch('/api/public/overview')).json();
    const g = d.gates?.G25 || {};
    const vals = { projects: d.projects, over10: d.share_over_10pct != null ? d.share_over_10pct * 100 : null,
      median: d.median_time_overrun_pct, mae: g.mae };
    $$('[data-count]').forEach(el => { el.dataset.to = vals[el.dataset.count] ?? ''; if (vals[el.dataset.count] == null) el.textContent = 'n/a'; });
    const base = $('[data-fill=base]'); if (base && g.baseline_mae != null) base.textContent = g.baseline_mae.toFixed(1);
    if (d.hypothetical) $('#numbers-note').textContent = `Figures come from the trained model card. ${d.hypothetical} of the ${d.projects} records are hypothetical scenarios; they are labelled in the app and in every result.`;
    $('#ev-rows').innerHTML = Object.entries(d.gates || {}).map(([k, v]) => `<tr><td>${k === 'G50' ? 'At 50% of contract time' : 'At 25% of contract time'}</td>
      <td class="good">${v.mae.toFixed(1)}</td><td>${v.baseline_mae.toFixed(1)}</td><td>${v.r2.toFixed(2)}</td><td>${v.auc.toFixed(2)}</td></tr>`).join('');
    if (!d.registration_open) { $('#reg-closed').hidden = false; setAuth('signin'); $('#at-register').hidden = true; }
    return true;
  } catch { $('#ev-rows').innerHTML = '<tr><td colspan="5">The model card could not be loaded.</td></tr>'; return false; }
}

function countUp(el) {
  const to = Number(el.dataset.to), dec = Number(el.dataset.dec || 0), suf = el.dataset.suffix || '';
  if (!Number.isFinite(to) || el.dataset.to === '') return;
  if (REDUCED || !window.gsap) { el.textContent = to.toFixed(dec) + suf; return; }
  const o = { v: 0 };
  gsap.to(o, { v: to, duration: 1.6, ease: 'power3.out', onUpdate: () => { el.textContent = o.v.toFixed(dec) + suf; } });
}

// =================================================================== isometric building for the BIM tab
function isoBuilding() {
  const svg = $('#v-bim'); if (!svg) return;
  const s = 26, cx = 260, cy = 250;
  const P = (x, y, z) => [cx + (x - y) * s * 0.866, cy + (x + y) * s * 0.5 - z * s];
  const poly = (pts, fill, cls = '') => `<polygon class="iso-face ${cls}" points="${pts.map(p => p.join(',')).join(' ')}" style="fill:${fill}"/>`;
  const risk = ['#8C9AA3', '#3DD68C', '#F2C94C', '#FF4D5E'];
  const shade = (hex, f) => '#' + [1, 3, 5].map(i => Math.round(parseInt(hex.slice(i, i + 2), 16) * f).toString(16).padStart(2, '0')).join('');
  let out = '';
  for (let z = 0; z < 4; z++) for (let x = 0; x < 3; x++) for (let y = 0; y < 3; y++) {
    const c = risk[z], hgt = 0.92, x0 = x * 1.05, y0 = y * 1.05, z0 = z * 1.05;
    const top = [P(x0, y0, z0 + hgt), P(x0 + 1, y0, z0 + hgt), P(x0 + 1, y0 + 1, z0 + hgt), P(x0, y0 + 1, z0 + hgt)];
    const left = [P(x0, y0 + 1, z0), P(x0 + 1, y0 + 1, z0), P(x0 + 1, y0 + 1, z0 + hgt), P(x0, y0 + 1, z0 + hgt)];
    const right = [P(x0 + 1, y0, z0), P(x0 + 1, y0 + 1, z0), P(x0 + 1, y0 + 1, z0 + hgt), P(x0 + 1, y0, z0 + hgt)];
    out += `<g class="cell" data-z="${z}">${poly(left, shade(c, 0.62))}${poly(right, shade(c, 0.8))}${poly(top, c)}</g>`;
  }
  svg.innerHTML = out + `<text x="40" y="40" class="lbl">risk by storey: grey done, green, amber, red</text>`;
}

// =================================================================== tabbed walkthrough
const ORDER = ['now', 'next', 'why', 'fix', 'live', 'bim'];
let cur = 'now', progTween = null, paused = false;

function playPanel(x) {
  if (REDUCED || !window.gsap) return;
  const p = $(`#xp-${x}`), G = gsap;
  G.fromTo(p.querySelector('.xtext'), { opacity: 0, x: -24 }, { opacity: 1, x: 0, duration: 0.6, ease: 'power3.out' });
  const draw = (el, d = 1.2, delay = 0) => { if (!el) return; const L = el.getTotalLength(); G.fromTo(el, { strokeDasharray: L, strokeDashoffset: L }, { strokeDashoffset: 0, duration: d, delay, ease: 'power2.inOut' }); };
  if (x === 'now') {
    draw(p.querySelector('.pv'), 1.3);
    G.fromTo(p.querySelectorAll('.vl, .lbl'), { opacity: 0 }, { opacity: 1, duration: 0.4, delay: 0.9, stagger: 0.08 });
    G.fromTo(p.querySelector('.gap'), { scaleX: 0, transformOrigin: 'left center' }, { scaleX: 1, duration: 0.8, delay: 1.2, ease: 'power3.out' });
    G.fromTo(p.querySelector('.gapline'), { scaleX: 0, transformOrigin: 'left center' }, { scaleX: 1, duration: 0.8, delay: 1.3, ease: 'power3.out' });
    G.fromTo(p.querySelector('.ev'), { scale: 0, transformOrigin: 'center' }, { scale: 1, duration: 0.5, delay: 1.1, ease: 'back.out(3)' });
    G.fromTo(p.querySelector('.big-t'), { opacity: 0, y: 12 }, { opacity: 1, y: 0, duration: 0.5, delay: 1.7 });
  }
  if (x === 'next') G.fromTo(p.querySelectorAll('.bar'), { scaleX: 0, transformOrigin: 'left center' }, { scaleX: 1, duration: 0.9, stagger: 0.18, ease: 'power3.out' });
  if (x === 'why') G.fromTo(p.querySelectorAll('rect'), { scaleX: 0, transformOrigin: 'left center' }, { scaleX: 1, duration: 0.55, stagger: 0.14, ease: 'power3.out' });
  if (x === 'fix') { draw(p.querySelector('.tc'), 1.4); G.fromTo(p.querySelector('.opt'), { scale: 0, transformOrigin: 'center' }, { scale: 1, delay: 1.2, duration: 0.6, ease: 'back.out(3)' }); }
  if (x === 'live') {
    draw(p.querySelector('.spark'), 1.2, 0.6);
    G.fromTo(p.querySelector('.packet'), { attr: { cx: 150 }, opacity: 1 }, { attr: { cx: 300 }, duration: 1.1, repeat: -1, repeatDelay: 0.5, ease: 'power1.inOut' });
    G.fromTo(p.querySelector('.psend'), { opacity: 0.5 }, { opacity: 1, duration: 0.55, repeat: -1, yoyo: true });
  }
  if (x === 'bim') G.fromTo(p.querySelectorAll('.cell'), { opacity: 0, y: -30 }, { opacity: 1, y: 0, duration: 0.5, stagger: { each: 0.035, from: 'start' }, ease: 'power3.out' });
}

function selectTab(x, { auto = false } = {}) {
  cur = x;
  $$('#xtabs [role=tab]').forEach(b => { const on = b.dataset.x === x; b.setAttribute('aria-selected', String(on)); b.tabIndex = on ? 0 : -1; b.querySelector('.prog').style.transform = 'scaleX(0)'; });
  $$('.xpanel').forEach(p => { p.hidden = p.dataset.x !== x; });
  if (window.gsap) gsap.killTweensOf('.xpanel *');
  playPanel(x);
  runProgress();
  if (!auto) paused = false;
}

function runProgress() {
  if (REDUCED || !window.gsap) return;
  progTween?.kill();
  const bar = $(`#xt-${cur} .prog`);
  progTween = gsap.fromTo(bar, { scaleX: 0 }, { scaleX: 1, duration: 7, ease: 'none', paused,
    onComplete: () => selectTab(ORDER[(ORDER.indexOf(cur) + 1) % ORDER.length], { auto: true }) });
}

function wireTabs() {
  const tabs = $$('#xtabs [role=tab]');
  tabs.forEach(b => b.addEventListener('click', () => selectTab(b.dataset.x)));
  $('#xtabs').addEventListener('keydown', e => {
    const i = ORDER.indexOf(cur);
    if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
      const n = ORDER[(i + (e.key === 'ArrowRight' ? 1 : ORDER.length - 1)) % ORDER.length];
      selectTab(n); $(`#xt-${n}`).focus(); e.preventDefault();
    }
  });
  const box = $('#how .wrap');
  box.addEventListener('pointerenter', () => { paused = true; progTween?.pause(); });
  box.addEventListener('pointerleave', () => { paused = false; progTween?.resume(); });
  box.addEventListener('focusin', () => { paused = true; progTween?.pause(); });
}

// =================================================================== scroll choreography
function scrollMotion() {
  const nav = $('#nav');
  const solid = () => nav.classList.toggle('solid', scrollY > 40);
  addEventListener('scroll', solid, { passive: true }); solid();
  $$('.feat article').forEach(a => a.addEventListener('pointermove', e => {
    const r = a.getBoundingClientRect(); a.style.setProperty('--mx', `${e.clientX - r.left}px`); a.style.setProperty('--my', `${e.clientY - r.top}px`);
  }));
  if (REDUCED || !window.gsap || !window.ScrollTrigger) {
    $$('[data-count]').forEach(countUp);
    $$('#steps li').forEach(li => li.classList.add('on'));
    return;
  }
  gsap.registerPlugin(ScrollTrigger);
  // hero headline: lines rise, then copy and HUD
  gsap.from('.h-split span', { yPercent: 110, opacity: 0, duration: 1.1, stagger: 0.09, ease: 'power4.out', delay: 0.15 });
  gsap.from(['.kicker', '.lede', '.cta-row', '.hud'], { y: 24, opacity: 0, duration: 0.9, stagger: 0.1, delay: 0.55, ease: 'power3.out' });
  gsap.to('.hero-copy', { yPercent: -18, opacity: 0.15, ease: 'none', scrollTrigger: { trigger: '.hero', start: 'top top', end: 'bottom top', scrub: true } });
  $$('.reveal-up').forEach(el => gsap.to(el, { opacity: 1, y: 0, duration: 0.9, ease: 'power3.out', scrollTrigger: { trigger: el, start: 'top 88%' } }));
  ScrollTrigger.create({ trigger: '.stats', start: 'top 80%', once: true, onEnter: () => $$('[data-count]').forEach(countUp) });
  // pinned pipeline: each step lights up in turn as you scroll
  const steps = $$('#steps li');
  ScrollTrigger.create({
    trigger: '.pipe', start: 'top top', end: '+=1400', pin: '.pipe-pin', scrub: 0.6,
    onUpdate: self => {
      const k = self.progress, n = Math.min(steps.length - 1, Math.floor(k * steps.length * 1.02));
      steps.forEach((li, i) => { li.classList.toggle('on', i <= n); li.classList.toggle('cur', i === n); });
      $('#pipe-fill').style.transform = `scaleX(${k})`;
    },
  });
  ScrollTrigger.create({ trigger: '#how', start: 'top 70%', once: true, onEnter: () => selectTab('now', { auto: true }) });
}

// =================================================================== sign in / create workspace
const NEXT = new URLSearchParams(location.search).get('next') === 'app' ? '/app' : '/app#projects';

function setAuth(a) {
  $('.auth-tabs').dataset.on = a;
  $$('.auth-tabs [role=tab]').forEach(b => b.setAttribute('aria-selected', String(b.dataset.a === a)));
  $$('#auth form').forEach(f => { f.hidden = f.dataset.a !== a; });
}

function strength(pw) {
  let s = 0;
  if (pw.length >= 10) s++;
  if (pw.length >= 14) s++;
  if (/[A-Z]/.test(pw) && /[a-z]/.test(pw)) s++;
  if (/\d/.test(pw) && /[^A-Za-z0-9]/.test(pw)) s++;
  return pw ? Math.max(1, s) : 0;
}

async function submit(form, path) {
  const err = form.querySelector('.err'), btn = form.querySelector('button[type=submit]');
  err.textContent = '';
  const body = Object.fromEntries(new FormData(form).entries());
  if (Object.values(body).some(v => !String(v).trim())) { err.textContent = 'Fill in every field.'; return; }
  btn.disabled = true; const label = btn.textContent; btn.textContent = 'One moment';
  try {
    const r = await fetch(path, { method: 'POST', headers: HDR, body: JSON.stringify(body) });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) {
      err.textContent = typeof d.detail === 'string' ? d.detail : 'Check the details and try again.';
      if (window.gsap && !REDUCED) gsap.fromTo(form, { x: -8 }, { x: 0, duration: 0.5, ease: 'elastic.out(1, 0.3)' });
      return;
    }
    btn.textContent = 'Opening your workspace';
    location.href = NEXT;
  } catch { err.textContent = 'The REVIVE server is not reachable.'; }
  finally { btn.disabled = false; if (btn.textContent === 'One moment') btn.textContent = label; }
}

async function wireAuth() {
  $$('.auth-tabs [role=tab]').forEach(b => b.addEventListener('click', () => setAuth(b.dataset.a)));
  $$('[data-auth]').forEach(a => a.addEventListener('click', () => setAuth(a.dataset.auth)));
  $('#f-register').addEventListener('submit', e => { e.preventDefault(); submit(e.target, '/api/auth/register'); });
  $('#f-signin').addEventListener('submit', e => { e.preventDefault(); submit(e.target, '/api/auth/login'); });
  $('#f-register [name=password]').addEventListener('input', e => { $('.pw').dataset.s = String(strength(e.target.value)); });
  if (location.hash === '#start' && new URLSearchParams(location.search).get('next')) setAuth('signin');
  if (new URLSearchParams(location.search).get('link') === 'invalid') {
    setAuth('signin');
    $('#f-signin .err').textContent = 'That admin link has expired or was already used. Run "python -m revive admin-link" again.';
  }
  try {
    const r = await fetch('/api/auth/me', { cache: 'no-store' });
    if (r.ok) {
      const { user } = await r.json();
      $('#si-who').textContent = `${user.name}, ${user.company_name}`;
      $('.auth-tabs').hidden = true; $$('#auth form').forEach(f => { f.hidden = true; }); $('#signed-in').hidden = false;
      $('#nav-cta').textContent = 'Open workspace'; $('#nav-cta').href = '/app'; $('#nav-cta').removeAttribute('data-auth');
      $('#nav-signin').hidden = true;
    }
  } catch { /* offline: the forms still show */ }
}

// =================================================================== boot
nightSite();
isoBuilding();
wireAuth();
wireTabs();
overview();
ready.then(() => { scrollMotion(); if (REDUCED || !window.gsap) selectTab('now', { auto: true }); });
