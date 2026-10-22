// REVIVE landing page (the intro before it is intro.js).
//  * hero: a procedural building assembles floor by floor under a tower crane in daylight, then a scan
//    plane sweeps up and recolours it by delay risk, then recovery activities pulse pink (Three.js)
//  * the HUD numbers follow that animation (labelled illustrative)
//  * real figures come from /api/public/overview (cross-validated model card), never hard-coded
//  * motion: Motion (vendored, the Framer Motion engine) for the intro, tabs, scroll and reveals
//  * sign in / create workspace talk to /api/auth/*
import * as THREE from 'three';
import { REDUCED, enter, plate, roving } from './tabs.js';

const M = globalThis.Motion;
const OUT = [0.16, 1, 0.3, 1];
document.documentElement.classList.add('js');
if (M && !REDUCED) document.documentElement.classList.add('motion');
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const HDR = { 'Content-Type': 'application/json', 'X-Revive-Request': '1' };

// =================================================================== 3D site in daylight (an architectural model in the hero frame)
function siteModel() {
  const canvas = $('#scene');
  let renderer;
  try { renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: 'high-performance' }); }
  catch { canvas.hidden = true; return null; }
  renderer.setPixelRatio(Math.min(devicePixelRatio, 1.75));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  const scene = new THREE.Scene();
  renderer.setClearColor(0x000000, 0);                 // the sky is the frame's CSS gradient underneath
  scene.fog = new THREE.Fog(0xE4E5E2, 60, 190);         // haze matches the bottom of that gradient, so the ground meets it
  const camera = new THREE.PerspectiveCamera(36, 1, 0.1, 500);
  const target = new THREE.Vector3(0, 9, 0);

  scene.add(new THREE.HemisphereLight(0xFFFFFF, 0xB9B3A8, 1.15));
  const key = new THREE.DirectionalLight(0xFFF3E0, 1.5); key.position.set(-40, 60, 30); scene.add(key);   // high sun
  const fill = new THREE.DirectionalLight(0xD6E4F5, 0.45); fill.position.set(40, 20, -30); scene.add(fill);

  // ground: a concrete plain that fades into the haze, so the horizon meets the sky
  const ground = new THREE.Mesh(new THREE.CircleGeometry(420, 64), new THREE.MeshStandardMaterial({ color: 0xD3CEC4, roughness: 0.95 }));
  ground.rotation.x = -Math.PI / 2; ground.position.y = -0.05; scene.add(ground);

  // ground: the setting-out grid and a yellow pool marking the site under the building
  const grid = new THREE.GridHelper(240, 120, 0x8E8A82, 0xB4AFA5);
  grid.material.transparent = true; grid.material.opacity = 0.45; scene.add(grid);
  const glowTex = (() => {
    const c = document.createElement('canvas'); c.width = c.height = 256;
    const g = c.getContext('2d'), r = g.createRadialGradient(128, 128, 0, 128, 128, 128);
    r.addColorStop(0, 'rgba(255,194,26,0.30)'); r.addColorStop(0.5, 'rgba(255,194,26,0.08)'); r.addColorStop(1, 'rgba(255,194,26,0)');
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
    const m = new THREE.Mesh(slabGeo, new THREE.MeshStandardMaterial({ color: 0xF2EFE9, roughness: 0.8, transparent: true, opacity: 0.9 }));
    m.position.set(0, (s + 1) * SH, 0);
    const e = new THREE.LineSegments(slabEdges, new THREE.LineBasicMaterial({ color: 0x2A2D31, transparent: true, opacity: 0.5 }));
    m.add(e); scene.add(m); slabs.push(m);
  }
  // risk colour of each storey after the scan (lower floors done, upper floors carry the delay)
  const C = { built: new THREE.Color(0xE9E5DD), done: new THREE.Color(0x9AA2AB), go: new THREE.Color(0x22B07A), watch: new THREE.Color(0xF2C230),
    risk: new THREE.Color(0xF07A2A), crit: new THREE.Color(0xE03A50), mark: new THREE.Color(0xE8378F), active: new THREE.Color(0xFFC21A) };
  const riskOf = [C.done, C.done, C.go, C.watch, C.risk, C.crit];
  const crashed = new Set([4, 5]);

  // scan plane
  const scan = new THREE.Mesh(new THREE.PlaneGeometry(BX * SP + 8, BZ * SP + 8), new THREE.MeshBasicMaterial({ color: 0x1F5FAD, transparent: true, opacity: 0.0, side: THREE.DoubleSide, depthWrite: false }));
  scan.rotation.x = -Math.PI / 2; scene.add(scan);
  const scanEdge = new THREE.LineSegments(new THREE.EdgesGeometry(scan.geometry), new THREE.LineBasicMaterial({ color: 0x1F5FAD, transparent: true, opacity: 0 }));
  scan.add(scanEdge);

  // tower crane in linework
  const crane = new THREE.Group(); crane.position.set(-22, 0, -14); scene.add(crane);
  const line = (geo, c = 0x2A2D31, o = 0.9) => new THREE.LineSegments(new THREE.EdgesGeometry(geo), new THREE.LineBasicMaterial({ color: c, transparent: true, opacity: o }));
  const H = 34;
  for (let y = 0; y < H; y += 2) { const seg = line(new THREE.BoxGeometry(1.2, 2, 1.2)); seg.position.y = y + 1; crane.add(seg); }
  const slew = new THREE.Group(); slew.position.y = H; crane.add(slew);
  const jib = line(new THREE.BoxGeometry(32, 1, 1)); jib.position.x = 15; slew.add(jib);
  const cjib = line(new THREE.BoxGeometry(10, 1, 1)); cjib.position.x = -6; slew.add(cjib);
  const cab = new THREE.Mesh(new THREE.BoxGeometry(1.6, 1.4, 1.6), new THREE.MeshBasicMaterial({ color: 0xFFC21A })); cab.position.set(0, -1, 0.4); slew.add(cab);
  const tip = new THREE.Mesh(new THREE.SphereGeometry(0.25, 8, 8), new THREE.MeshBasicMaterial({ color: 0xE03A50 })); tip.position.set(31, 0.8, 0); slew.add(tip);
  const trolley = new THREE.Group(); slew.add(trolley);
  const cableGeo = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3(0, -10, 0)]);
  const cable = new THREE.Line(cableGeo, new THREE.LineBasicMaterial({ color: 0x2A2D31, transparent: true, opacity: 0.7 })); trolley.add(cable);
  const hook = new THREE.Mesh(new THREE.BoxGeometry(0.7, 0.7, 0.7), new THREE.MeshBasicMaterial({ color: 0x2A2D31 })); trolley.add(hook);
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
    scan.material.opacity = scanP > 0 && scanP < 1.05 ? 0.16 : 0;
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
    camera.zoom = w / h < 0.9 ? 0.78 : 1; camera.updateProjectionMatrix();   // narrow frames pull back
  }
  new ResizeObserver(resize).observe(canvas); resize();
  // behind the intro cover the scene draws one frame and waits: the building starts rising as the cover lifts
  const root = document.documentElement, covered = () => root.classList.contains('intro');
  const canRun = () => !REDUCED && !covered();
  let visible = true, raf = 0, t0 = performance.now();
  new IntersectionObserver(([e]) => { visible = e.isIntersecting; if (visible && !raf && canRun()) loop(); }).observe(canvas);
  function place(t) {
    px += (tx - px) * 0.04; py += (ty - py) * 0.04;
    const a = 0.75 + t * 0.035 + px * 0.5;
    camera.position.set(Math.cos(a) * 74, 24 + py * -4, Math.sin(a) * 74);   // a model-maker's eye: above the site, the crane against the sky
    camera.lookAt(target);
  }
  function loop() {
    raf = 0;
    if (!visible || document.hidden) return;
    const t = (performance.now() - t0) / 1000;
    frame(t); place(t); renderer.render(scene, camera);
    raf = requestAnimationFrame(loop);
  }
  document.addEventListener('visibilitychange', () => { if (!document.hidden && visible && !raf && canRun()) loop(); });
  if (REDUCED) { frame(12.5); place(0); renderer.render(scene, camera); }
  else if (covered()) {
    frame(0); place(0); renderer.render(scene, camera);
    new MutationObserver((_, mo) => { if (!covered()) { mo.disconnect(); t0 = performance.now(); loop(); } })
      .observe(root, { attributes: true, attributeFilter: ['class'] });
  } else loop();
  return true;
}

// =================================================================== real numbers (model card)
async function overview() {
  try {
    const d = await (await fetch('/api/public/overview')).json();
    const g = d.gates?.G25 || {};
    const vals = { projects: d.records ?? d.projects, over10: d.share_over_10pct != null ? d.share_over_10pct * 100 : null,
      median: d.median_time_overrun_pct, mae: g.mae };
    $$('[data-count]').forEach(el => {
      const v = vals[el.dataset.count];
      if (v == null) { el.textContent = 'n/a'; return; }
      el.dataset.to = v;
      if (M && !REDUCED) { const stop = M.inView(el, () => { countUp(el); stop(); }); } else countUp(el);
    });
    const base = $('[data-fill=base]');
    if (base) base.textContent = g.baseline_mae != null ? g.baseline_mae.toFixed(1) : 'n/a';
    $('#numbers-note').textContent = `Figures come from the trained model card. The survey holds ${d.records ?? d.projects} records, ${d.hypothetical || 0} of them hypothetical scenarios (labelled wherever they appear). The model is trained and tested on the ${d.projects} real completed projects only.`;
    $('#ev-rows').innerHTML = Object.entries(d.gates || {}).map(([k, v]) => `<tr><td>${k === 'G50' ? 'At 50% of contract time' : 'At 25% of contract time'}</td>
      <td class="good">${v.mae.toFixed(1)}</td><td>${v.baseline_mae.toFixed(1)}</td><td>${v.r2.toFixed(2)}</td><td>${v.loco_r2 == null ? '\u2014' : v.loco_r2.toFixed(2)}</td><td>${v.auc.toFixed(2)}</td></tr>`).join('');
    if (!d.registration_open) { $('#reg-closed').hidden = false; $('#at-register').hidden = true; setAuth('signin'); }
  } catch {
    $('#ev-rows').innerHTML = '<tr><td colspan="6">The model card could not be loaded.</td></tr>';
    $$('[data-count], [data-fill]').forEach(el => { el.textContent = 'n/a'; });
  }
}

function countUp(el) {
  const to = Number(el.dataset.to), dec = Number(el.dataset.dec || 0), suf = el.dataset.suffix || '';
  const show = v => { el.textContent = v.toFixed(dec) + suf; };
  if (!M || REDUCED) { show(to); return; }
  M.animate(0, to, { duration: 1.6, ease: OUT, onUpdate: show });
}

// =================================================================== isometric building for the BIM tab
function isoBuilding() {
  const svg = $('#v-bim'); if (!svg) return;
  const s = 26, cx = 260, cy = 250;
  const P = (x, y, z) => [cx + (x - y) * s * 0.866, cy + (x + y) * s * 0.5 - z * s];
  const poly = (pts, fill, cls = '') => `<polygon class="iso-face ${cls}" points="${pts.map(p => p.join(',')).join(' ')}" style="fill:${fill}"/>`;
  const risk = ['#8E98A3', '#34D399', '#F5D547', '#FF5468'];
  const shade = (hex, f) => '#' + [1, 3, 5].map(i => Math.round(parseInt(hex.slice(i, i + 2), 16) * f).toString(16).padStart(2, '0')).join('');
  let out = '';
  for (let z = 0; z < 4; z++) for (let x = 0; x < 3; x++) for (let y = 0; y < 3; y++) {
    const c = risk[z], hgt = 0.92, x0 = x * 1.05, y0 = y * 1.05, z0 = z * 1.05;
    const top = [P(x0, y0, z0 + hgt), P(x0 + 1, y0, z0 + hgt), P(x0 + 1, y0 + 1, z0 + hgt), P(x0, y0 + 1, z0 + hgt)];
    const left = [P(x0, y0 + 1, z0), P(x0 + 1, y0 + 1, z0), P(x0 + 1, y0 + 1, z0 + hgt), P(x0, y0 + 1, z0 + hgt)];
    const right = [P(x0 + 1, y0, z0), P(x0 + 1, y0 + 1, z0), P(x0 + 1, y0 + 1, z0 + hgt), P(x0 + 1, y0, z0 + hgt)];
    out += `<g class="cell" data-z="${z}">${poly(left, shade(c, 0.62))}${poly(right, shade(c, 0.8))}${poly(top, c)}</g>`;
  }
  svg.innerHTML = out + '<text x="40" y="40" class="lbl">risk by storey: grey done, green, amber, red</text>';
}

// =================================================================== tabbed walkthrough
const ORDER = ['now', 'next', 'why', 'fix', 'live', 'bim'];
const AUTO_S = 7;            // seconds per question while nobody is interacting
let cur = 'now', prog = null, paused = false, loops = [];

/** Each panel's diagram builds itself the way the analysis does: curves draw, bars grow, the optimum lands. */
function playPanel(x, dir) {
  loops.forEach(l => l.stop()); loops = [];
  if (!M || REDUCED) return;
  const p = $(`#xp-${x}`), A = M.animate, S = M.stagger;
  enter($('.xtext', p), dir, { distance: 36, blur: 6, duration: 0.55, stagger: 0.06, items: [...$$('h3, p', p), ...$$('li', p)] });
  A($('.xvis', p), { opacity: [0, 1], scale: [0.96, 1], y: [14, 0], filter: ['blur(8px)', 'blur(0px)'] }, { duration: 0.65, ease: OUT });
  const draw = (el, duration = 1.2, delay = 0) => {
    if (!el) return;
    const L = el.getTotalLength();
    el.style.strokeDasharray = L;
    A(el, { strokeDashoffset: [L, 0] }, { duration, delay, ease: [0.65, 0, 0.35, 1] });
  };
  const grow = (els, opts) => { els.forEach(e => { e.style.transformOrigin = 'left center'; }); A(els, { scaleX: [0, 1] }, { duration: 0.8, ease: OUT, ...opts }); };
  const pop = (el, delay) => el && A(el, { scale: [0, 1] }, { type: 'spring', stiffness: 420, damping: 14, delay });
  if (x === 'now') {
    draw($('.pv', p), 1.3);
    A($$('.vl, .lbl', p), { opacity: [0, 1] }, { duration: 0.4, delay: S(0.08, { startDelay: 0.9 }) });
    grow([$('.gap', p)], { delay: 1.2 }); grow([$('.gapline', p)], { delay: 1.3 });
    pop($('.ev', p), 1.1);
    A($('.big-t', p), { opacity: [0, 1], y: [12, 0] }, { duration: 0.5, delay: 1.7, ease: OUT });
  }
  if (x === 'next') grow($$('.bar', p), { duration: 0.9, delay: S(0.18) });
  if (x === 'why') grow($$('rect', p), { duration: 0.55, delay: S(0.14) });
  if (x === 'fix') { draw($('.tc', p), 1.4); pop($('.opt', p), 1.2); }
  if (x === 'live') {
    draw($('.spark', p), 1.2, 0.6);
    loops.push(A($('.packet', p), { x: [0, 150], opacity: [1, 1, 0] }, { duration: 1.1, repeat: Infinity, repeatDelay: 0.5, ease: 'easeInOut' }));
    loops.push(A($('.psend', p), { opacity: [0.5, 1] }, { duration: 0.55, repeat: Infinity, repeatType: 'reverse' }));
  }
  if (x === 'bim') A($$('.cell', p), { opacity: [0, 1], y: [-30, 0] }, { duration: 0.5, delay: S(0.035), ease: OUT });
}

/** Mark a tab's autoplay cycle as complete (its progress bar is drawn by runProgress). */
function ring(b, k) { b?.classList.toggle('done', k >= 0.995); }

function selectTab(x, { auto = false } = {}) {
  const dir = Math.sign(ORDER.indexOf(x) - ORDER.indexOf(cur));
  cur = x;
  $$('#xtabs [role=tab]').forEach(b => {
    const on = b.dataset.x === x;
    b.setAttribute('aria-selected', String(on)); b.tabIndex = on ? 0 : -1;
    b.querySelector('.prog').style.transform = 'scaleX(0)';
    ring(b, on && (!M || REDUCED) ? 1 : 0);
  });
  plate($('.xt-ind'), $(`#xt-${x}`));
  $$('.xpanel').forEach(p => { p.hidden = p.dataset.x !== x; });
  playPanel(x, dir);
  if (!auto) paused = false;
  runProgress();
}

/** Autoplay: the selected tab's ring and bar fill over AUTO_S seconds, then the next question opens. */
function runProgress() {
  prog?.stop(); prog = null;
  if (!M || REDUCED) return;
  const x = cur, btn = $(`#xt-${x}`), bar = $('.prog', btn);
  prog = M.animate(0, 1, { duration: AUTO_S, ease: 'linear',
    onUpdate: k => { if (cur === x) { bar.style.transform = `scaleX(${k})`; ring(btn, k); } },   // a late frame never refills a tab already left
    onComplete: () => selectTab(ORDER[(ORDER.indexOf(cur) + 1) % ORDER.length], { auto: true }) });
  if (paused) prog.pause();
}

const hold = on => { paused = on; if (on) prog?.pause(); else prog?.play(); };

function wireTabs() {
  const box = $('#xtabs'), tabs = () => $$('#xtabs [role=tab]');
  tabs().forEach(b => b.addEventListener('click', () => selectTab(b.dataset.x)));
  roving(box, tabs, { activate: t => selectTab(t.dataset.x) });
  new ResizeObserver(() => plate($('.xt-ind'), $(`#xt-${cur}`), { instant: true })).observe(box);
  box.addEventListener('pointermove', e => {          // a floodlight that follows the pointer across the tab strip
    const r = box.getBoundingClientRect();
    box.style.setProperty('--mx', `${e.clientX - r.left}px`); box.style.setProperty('--my', `${e.clientY - r.top}px`);
  }, { passive: true });
  const how = $('#how .wrap');
  how.addEventListener('pointerenter', () => hold(true));
  how.addEventListener('pointerleave', () => hold(false));
  how.addEventListener('focusin', () => hold(true));
  if (!M || REDUCED) { selectTab('now', { auto: true }); return; }
  let started = false;                                // start when the section is reached, pause while it is away
  M.inView('#how', () => {
    if (!started) { started = true; selectTab('now', { auto: true }); } else if (!paused) prog?.play();
    return () => prog?.pause();
  }, { amount: 0.25 });
}

// =================================================================== scroll
function scrollMotion() {
  const nav = $('#nav');
  if (!M) { nav.classList.add('solid'); return; }
  M.scroll((_, info) => nav.classList.toggle('solid', info.y.current > 40));
  if (REDUCED) { $$('#steps li').forEach(li => li.classList.add('on')); return; }
  // the hero frame eases back as the page scrolls away from it
  M.scroll(M.animate($('.hero-frame'), { scale: [1, 0.96], opacity: [1, 0.6] }, { ease: 'linear' }), { target: $('.hero'), offset: ['start start', 'end start'] });
  M.inView('.reveal-up', el => { M.animate(el, { opacity: [0, 1], y: [40, 0] }, { duration: 0.9, ease: OUT }); }, { margin: '0px 0px -10% 0px' });
  // site to decision: the section stays in view (CSS sticky) while each step lights up in turn
  const steps = $$('#steps li'), fill = $('#pipe-fill');
  if (matchMedia('(max-width: 640px)').matches) { steps.forEach(li => li.classList.add('on')); return; }
  M.scroll(k => {
    const n = Math.min(steps.length - 1, Math.floor(k * steps.length * 1.02));
    steps.forEach((li, i) => { li.classList.toggle('on', i <= n); li.classList.toggle('cur', i === n); });
    fill.style.transform = `scaleX(${k})`;
  }, { target: $('.pipe'), offset: ['start start', 'end end'] });
}

// =================================================================== sign in / create workspace
const NEXT = new URLSearchParams(location.search).get('next') === 'app' ? '/app' : '/app#projects';

function setAuth(a) {
  $$('.auth-tabs [role=tab]').forEach(b => { const on = b.dataset.a === a; b.setAttribute('aria-selected', String(on)); b.tabIndex = on ? 0 : -1; });
  const form = $(`#auth form[data-a="${a}"]`), was = form.hidden;
  $$('#auth form').forEach(f => { f.hidden = f.dataset.a !== a; });
  plate($('.auth-ind'), $(`.auth-tabs [data-a="${a}"]`));
  if (was) enter(form, a === 'signin' ? 1 : -1, { distance: 20, duration: 0.3, stagger: 0.03 });
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
  const err = $('.err', form), btn = $('button[type=submit]', form);
  err.textContent = '';
  const body = Object.fromEntries(new FormData(form).entries());
  if (Object.values(body).some(v => !String(v).trim())) { err.textContent = 'Fill in every field.'; return; }
  btn.disabled = true; const label = btn.textContent; btn.textContent = 'One moment';
  try {
    const r = await fetch(path, { method: 'POST', headers: HDR, body: JSON.stringify(body) });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) {
      err.textContent = typeof d.detail === 'string' ? d.detail : 'Check the details and try again.';
      if (M && !REDUCED) M.animate(form, { x: [0, -8, 7, -5, 3, 0] }, { duration: 0.45, ease: 'easeOut' });
      return;
    }
    btn.textContent = 'Opening your workspace';
    location.href = NEXT;
  } catch { err.textContent = 'The REVIVE server is not reachable.'; }
  finally { btn.disabled = false; if (btn.textContent === 'One moment') btn.textContent = label; }
}

async function wireAuth() {
  const tabs = () => $$('.auth-tabs [role=tab]');
  tabs().forEach(b => b.addEventListener('click', () => setAuth(b.dataset.a)));
  roving($('.auth-tabs'), tabs, { activate: t => setAuth(t.dataset.a) });
  new ResizeObserver(() => plate($('.auth-ind'), $('.auth-tabs [aria-selected=true]'), { instant: true })).observe($('.auth-tabs'));
  $$('[data-auth]').forEach(a => a.addEventListener('click', () => setAuth(a.dataset.auth)));
  $('#f-register').addEventListener('submit', e => { e.preventDefault(); submit(e.target, '/api/auth/register'); });
  $('#f-signin').addEventListener('submit', e => { e.preventDefault(); submit(e.target, '/api/auth/login'); });
  $('#f-register [name=password]').addEventListener('input', e => { $('.pw').dataset.s = String(strength(e.target.value)); });
  const q = new URLSearchParams(location.search);
  if (location.hash === '#start' && q.get('next')) setAuth('signin');
  if (q.get('link') === 'invalid') {
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
siteModel();
isoBuilding();
wireAuth();
plate($('.xt-ind'), $('#xt-now'), { instant: true });
wireTabs();
overview();
scrollMotion();
