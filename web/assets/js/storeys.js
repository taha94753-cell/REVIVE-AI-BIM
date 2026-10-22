// Storey explorer on the landing page (section #model): the same six-storey frame as the hero, pulled apart storey
// by storey so each one can be read on its own.
//  * scroll through the section and the storeys separate (an exploded axonometric); drag sideways to turn the block
//  * choose a plan (baseline, forecast, recovered) and every storey takes its delay band; recovered storeys go pink
//  * hover a storey for a glass card (a port of 21st.dev's liquid-glass-hover-card), click it or its row to slide it
//    out like a drawer with its readout
// The storey figures are illustrative and labelled so on the page. The storey list in the HTML is the real control
// and the fallback: without WebGL or script it still reads, and keyboard users select storeys from it.
import * as THREE from 'three';
import { REDUCED, plate } from './tabs.js';
import { glass, glassAll } from './glass.js';

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

// illustrative: forecast slip of each storey's finish (days) and the days the recovery plan buys back
const STOREYS = [
  { name: 'Ground', short: 'G', act: 'Raft, ground columns and slab', fore: 0, crash: 0, action: 'Complete' },
  { name: 'Level 1', short: 'L1', act: 'Level 1 columns, beams and slab', fore: 2, crash: 0, action: 'Within float, no action' },
  { name: 'Level 2', short: 'L2', act: 'Level 2 frame, interim payment paid late', fore: 5, crash: 1, action: 'Weekend pour' },
  { name: 'Level 3', short: 'L3', act: 'Level 3 frame, rebar delivery held', fore: 9, crash: 5, action: 'Second formwork set' },
  { name: 'Level 4', short: 'L4', act: 'Level 4 frame and services first fix', fore: 14, crash: 11, action: 'Extra steel-fixing gang' },
  { name: 'Roof', short: 'R', act: 'Roof slab, parapet and plant base', fore: 18, crash: 15, action: 'Night pour and a second pump' },
];
const PLAN_NAME = { base: 'Baseline', fore: 'Forecast', rec: 'Recovered' };
const slipOf = (st, plan) => plan === 'base' ? 0 : plan === 'fore' ? st.fore : st.fore - st.crash;
const bandOf = d => d <= 2 ? 'go' : d <= 6 ? 'watch' : d <= 12 ? 'risk' : 'crit';
const BAND_TEXT = { go: 'On plan', watch: 'Watch', risk: 'At risk', crit: 'Critical', mark: 'Recovered' };
const fmt = d => (d > 0 ? `+${d} d` : '0 d');

export function storeyExplorer() {
  const section = $('#model'), canvas = $('#model3d');
  if (!section || !canvas) return;
  const frameEl = canvas.parentElement;
  const rows = [];                                       // indexed by storey; the list itself runs roof first
  $$('#storeys button').forEach(b => { rows[Number(b.dataset.s)] = b; });
  const planBtns = $$('.plans button');
  const readout = $('#ro');
  let plan = 'fore', selected = -1, hovered = -1;

  glassAll(section);

  // ------------------------------------------------------------------ the HTML side: rows, plan switch, readout
  function paintRows() {
    rows.forEach((b, s) => {
      const st = STOREYS[s], d = slipOf(st, plan);
      const band = plan === 'rec' && st.crash ? 'mark' : bandOf(d);
      const em = b.querySelector('em');
      em.className = `d ${band}`;
      em.textContent = plan === 'rec' && st.crash ? `${fmt(d)}, ${st.crash} d back` : fmt(d);
      b.setAttribute('aria-pressed', String(s === selected));
    });
  }
  function paintReadout() {
    const t = readout.querySelector('[data-ro=t]'), a = readout.querySelector('[data-ro=a]'), dl = readout.querySelector('dl');
    if (selected < 0) {
      const fin = slipOf(STOREYS[5], plan), back = STOREYS[5].crash;
      t.textContent = `Whole block, ${PLAN_NAME[plan].toLowerCase()}`;
      a.textContent = plan === 'base' ? 'Every storey finishes on the baseline date.'
        : plan === 'fore' ? 'Late storeys stack up: the roof finishes last.' : 'Crashing the upper three storeys buys most of it back.';
      dl.innerHTML = `<div><dt>Finish</dt><dd class="${plan === 'rec' ? 'mark' : bandOf(fin)}">${fmt(fin)}</dd></div>`
        + `<div><dt>Bought back</dt><dd>${plan === 'rec' ? `${back} d` : 'none'}</dd></div>`;
      return;
    }
    const st = STOREYS[selected], d = slipOf(st, plan);
    t.textContent = `${st.name}, ${PLAN_NAME[plan].toLowerCase()}`;
    a.textContent = st.act;
    dl.innerHTML = `<div><dt>Finish slip</dt><dd class="${plan === 'rec' && st.crash ? 'mark' : bandOf(d)}">${fmt(d)}</dd></div>`
      + `<div><dt>${plan === 'rec' ? 'Bought back' : 'Recovery action'}</dt><dd class="small">${plan === 'rec' ? `${st.crash} d` : st.action}</dd></div>`;
  }
  function setPlan(p) {
    plan = p;
    planBtns.forEach(b => b.setAttribute('aria-pressed', String(b.dataset.plan === p)));
    plate($('.plans .plan-ind'), $(`.plans button[data-plan=${p}]`));
    paintRows(); paintReadout(); retint(); paintTags();
  }
  function select(s) {
    selected = s === selected ? -1 : s;
    if (selected >= 0) drawerDir.set(Math.cos(yaw) * 0.35 + Math.sin(yaw), 0, Math.sin(yaw) * 0.35 - Math.cos(yaw)).normalize();   // out to the viewer's right, a little toward them
    paintRows(); paintReadout(); paintTags(); wake();
  }
  planBtns.forEach(b => b.addEventListener('click', () => setPlan(b.dataset.plan)));
  rows.forEach((b, s) => {
    b.addEventListener('click', () => select(s));
    b.addEventListener('pointerenter', () => { hovered = s; paintTags(); wake(); });
    b.addEventListener('pointerleave', () => { hovered = -1; paintTags(); wake(); });
  });
  new ResizeObserver(() => plate($('.plans .plan-ind'), $('.plans button[aria-pressed=true]'), { instant: true })).observe($('.plans'));

  // ------------------------------------------------------------------ the 3D side
  let renderer;
  try { renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: 'high-performance' }); }
  catch { frameEl.classList.add('no-gl'); paintRows(); paintReadout(); return; }
  renderer.setPixelRatio(Math.min(devicePixelRatio, 1.75));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.08;
  renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.setClearColor(0x000000, 0);
  const scene = new THREE.Scene();
  scene.fog = new THREE.Fog(0xE7E4DE, 90, 220);
  const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 500);

  // something for the steel and the concrete sheen to reflect: a studio sky, light overhead, warm floor below
  const sky = document.createElement('canvas'); sky.width = 16; sky.height = 256;
  const sg = sky.getContext('2d'), sgr = sg.createLinearGradient(0, 0, 0, 256);
  sgr.addColorStop(0, '#9FB3C6'); sgr.addColorStop(0.45, '#EEF1F3'); sgr.addColorStop(0.52, '#D8D3CA'); sgr.addColorStop(1, '#7A746B');
  sg.fillStyle = sgr; sg.fillRect(0, 0, 16, 256);
  const skyTex = new THREE.CanvasTexture(sky); skyTex.mapping = THREE.EquirectangularReflectionMapping; skyTex.colorSpace = THREE.SRGBColorSpace;
  scene.environment = new THREE.PMREMGenerator(renderer).fromEquirectangular(skyTex).texture;
  scene.add(new THREE.HemisphereLight(0xEFF3F8, 0xA49D90, 0.6));
  const sun = new THREE.DirectionalLight(0xFFF1DC, 2.3);
  sun.position.set(38, 70, 30); sun.castShadow = true; sun.shadow.mapSize.set(2048, 2048);
  sun.shadow.bias = -0.0004; sun.shadow.normalBias = 0.03;
  Object.assign(sun.shadow.camera, { left: -40, right: 40, top: 50, bottom: -30, near: 1, far: 220 });
  scene.add(sun);
  const fill = new THREE.DirectionalLight(0xC9D8EA, 0.45); fill.position.set(-40, 20, -30); scene.add(fill);

  // cast-in-place concrete: a pale grey with pour marks and pinholes, and the same pattern as a little bump
  function concreteTex(seed) {
    const c = document.createElement('canvas'); c.width = c.height = 256;
    const g = c.getContext('2d');
    g.fillStyle = '#C9C5BD'; g.fillRect(0, 0, 256, 256);
    let r = seed;
    const rnd = () => ((r = (r * 16807) % 2147483647) / 2147483647);
    for (let i = 0; i < 2600; i++) {
      const v = 150 + rnd() * 70 | 0;
      g.fillStyle = `rgba(${v},${v - 3},${v - 8},${0.08 + rnd() * 0.12})`;
      const s = 1 + rnd() * 9; g.fillRect(rnd() * 256, rnd() * 256, s, s);
    }
    g.fillStyle = 'rgba(70,66,60,.35)';
    for (let i = 0; i < 260; i++) { g.beginPath(); g.arc(rnd() * 256, rnd() * 256, 0.6 + rnd() * 0.9, 0, 7); g.fill(); }
    g.strokeStyle = 'rgba(90,86,80,.10)'; g.lineWidth = 2;                       // shutter joints of the formwork
    for (let x = 0; x < 256; x += 64) { g.beginPath(); g.moveTo(x, 0); g.lineTo(x, 256); g.stroke(); }
    const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.wrapS = t.wrapT = THREE.RepeatWrapping; return t;
  }
  const texA = concreteTex(7), texB = concreteTex(31);
  const std = (color, rough, metal = 0, extra = {}) => new THREE.MeshStandardMaterial({ color, roughness: rough, metalness: metal, ...extra });
  const box = (w, h, d) => new THREE.BoxGeometry(w, h, d);

  const BX = 4, BZ = 3, SP = 6, SH = 3.6, NS = STOREYS.length, HX = BX * SP / 2, HZ = BZ * SP / 2;
  const W = BX * SP + 0.7, D = BZ * SP + 0.7, SLAB = 0.28, CH = SH - SLAB;

  // site: a paved plate under the block and a shadow catcher that fades into the frame
  const site = new THREE.Mesh(box(W + 18, 0.5, D + 16), std(0xD3CEC4, 0.95, 0, { map: texB }));
  site.position.y = -0.25; site.receiveShadow = true; scene.add(site);
  const catcher = new THREE.Mesh(new THREE.PlaneGeometry(300, 300), new THREE.ShadowMaterial({ opacity: 0.16 }));
  catcher.rotation.x = -Math.PI / 2; catcher.position.y = -0.51; catcher.receiveShadow = true; scene.add(catcher);
  const raft = new THREE.Mesh(box(W + 1.2, 0.6, D + 1.2), std(0xB9B4AB, 0.9, 0, { map: texA }));
  raft.position.y = 0.3; raft.castShadow = raft.receiveShadow = true; scene.add(raft);

  const BASE = new THREE.Color(0xFFFFFF);
  const TINT = { go: new THREE.Color(0x3BBF87), watch: new THREE.Color(0xF2C230), risk: new THREE.Color(0xF07A2A), crit: new THREE.Color(0xE03A50), mark: new THREE.Color(0xE8378F) };
  const hiVis = std(0xF07A2A, 0.6), helmet = std(0xF5F3EE, 0.35), steelBar = std(0x6E4B3A, 0.55, 0.6);
  const barrier = std(0xE8B517, 0.5, 0.1), post = std(0x2F3236, 0.5, 0.6);

  const levels = [];
  const hitMat = new THREE.MeshBasicMaterial({ visible: false });
  for (let s = 0; s < NS; s++) {
    const g = new THREE.Group(); scene.add(g);
    const frameMat = std(0xFFFFFF, 0.86, 0, { map: texA, bumpMap: texA, bumpScale: 0.6 });
    const slabMat = std(0xFFFFFF, 0.82, 0, { map: texB, bumpMap: texB, bumpScale: 0.5 });
    slabMat.map = texB.clone(); slabMat.map.repeat.set(4, 3); slabMat.map.needsUpdate = true;
    // columns
    const cols = new THREE.InstancedMesh(box(0.55, CH, 0.55), frameMat, (BX + 1) * (BZ + 1));
    const m4 = new THREE.Matrix4(); let n = 0;
    for (let i = 0; i <= BX; i++) for (let k = 0; k <= BZ; k++) cols.setMatrixAt(n++, m4.makeTranslation(-HX + i * SP, 0.6 + CH / 2, -HZ + k * SP));
    // downstand beams both ways
    const bx = new THREE.InstancedMesh(box(SP, 0.5, 0.38), frameMat, BX * (BZ + 1)); n = 0;
    for (let i = 0; i < BX; i++) for (let k = 0; k <= BZ; k++) bx.setMatrixAt(n++, m4.makeTranslation(-HX + (i + 0.5) * SP, 0.6 + CH - 0.25, -HZ + k * SP));
    const bz = new THREE.InstancedMesh(box(0.38, 0.5, SP), frameMat, (BX + 1) * BZ); n = 0;
    for (let i = 0; i <= BX; i++) for (let k = 0; k < BZ; k++) bz.setMatrixAt(n++, m4.makeTranslation(-HX + i * SP, 0.6 + CH - 0.25, -HZ + (k + 0.5) * SP));
    const slab = new THREE.Mesh(box(W, SLAB, D), slabMat); slab.position.y = 0.6 + CH + SLAB / 2;
    // lift and stair core: four walls with a door opening on the front
    const core = new THREE.Group(), cx = -3, cz = -3, cw = 5, t = 0.25;
    [[cx, cz - cw / 2, cw, t], [cx - cw / 2, cz, t, cw], [cx + cw / 2, cz, t, cw]].forEach(([x, z, w, d]) => {
      const m = new THREE.Mesh(box(w, CH, d), frameMat); m.position.set(x, 0.6 + CH / 2, z); core.add(m);
    });
    [[cx - 1.6, 1.8], [cx + 1.6, 1.8]].forEach(([x, w]) => { const m = new THREE.Mesh(box(w, CH, t), frameMat); m.position.set(x, 0.6 + CH / 2, cz + cw / 2); core.add(m); });
    for (const m of [cols, bx, bz, slab, ...core.children]) { m.castShadow = m.receiveShadow = true; }
    g.add(cols, bx, bz, slab, core);

    // people for scale: a crew in hi-vis on the slab of the storeys still being worked
    if (s >= 2) {
      const crew = s === NS - 1 ? 4 : 2;
      for (let w = 0; w < crew; w++) {
        const man = new THREE.Group();
        const body = new THREE.Mesh(new THREE.CapsuleGeometry(0.24, 0.85, 4, 10), hiVis); body.position.y = 0.67;
        const head = new THREE.Mesh(new THREE.SphereGeometry(0.17, 14, 10), helmet); head.position.y = 1.45;
        body.castShadow = head.castShadow = true; man.add(body, head);
        const a = s * 2.1 + w * 1.7;
        man.position.set(Math.cos(a) * (6 + w * 2.4), slab.position.y + SLAB / 2, Math.sin(a) * 4.5);
        g.add(man);
      }
    }
    // the roof is the slab being poured: edge protection all round and starter bars up out of every column
    if (s === NS - 1) {
      const top = slab.position.y + SLAB / 2, posts = [], rails = [];
      for (const [x0, z0, x1, z1] of [[-W / 2, -D / 2, W / 2, -D / 2], [W / 2, -D / 2, W / 2, D / 2], [W / 2, D / 2, -W / 2, D / 2], [-W / 2, D / 2, -W / 2, -D / 2]]) {
        const len = Math.hypot(x1 - x0, z1 - z0), steps = Math.round(len / 3);
        for (let i = 0; i < steps; i++) posts.push([x0 + (x1 - x0) * i / steps, z0 + (z1 - z0) * i / steps]);
        for (const h of [0.55, 1.05]) rails.push({ x: (x0 + x1) / 2, z: (z0 + z1) / 2, w: Math.abs(x1 - x0) + 0.06, d: Math.abs(z1 - z0) + 0.06, h });
      }
      const pm = new THREE.InstancedMesh(box(0.07, 1.15, 0.07), post, posts.length);
      posts.forEach(([x, z], i) => pm.setMatrixAt(i, m4.makeTranslation(x, top + 0.575, z)));
      pm.castShadow = true; g.add(pm);
      for (const r of rails) { const m = new THREE.Mesh(box(r.w, 0.09, r.d), barrier); m.position.set(r.x, top + r.h, r.z); m.castShadow = true; g.add(m); }
      const bars = new THREE.InstancedMesh(new THREE.CylinderGeometry(0.035, 0.035, 1.3, 6), steelBar, (BX + 1) * (BZ + 1) * 4); n = 0;
      for (let i = 0; i <= BX; i++) for (let k = 0; k <= BZ; k++) for (const [dx, dz] of [[-0.17, -0.17], [0.17, -0.17], [-0.17, 0.17], [0.17, 0.17]]) {
        bars.setMatrixAt(n++, m4.makeTranslation(-HX + i * SP + dx, top + 0.65, -HZ + k * SP + dz));
      }
      bars.castShadow = true; g.add(bars);
    }
    const hit = new THREE.Mesh(box(W + 0.6, SH, D + 0.6), hitMat); hit.position.y = 0.6 + SH / 2; hit.userData.s = s; g.add(hit);
    levels.push({ g, mats: [frameMat, slabMat], hit, cur: new THREE.Color(1, 1, 1), goal: new THREE.Color(1, 1, 1), lift: 0, slide: 0, glow: 0 });
  }

  function retint() {
    levels.forEach((L, s) => {
      const st = STOREYS[s], d = slipOf(st, plan);
      const key = plan === 'base' ? null : plan === 'rec' && st.crash ? 'mark' : bandOf(d);
      L.goal.copy(BASE); if (key) L.goal.lerp(TINT[key], key === 'go' ? 0.4 : 0.55);
    });
    wake();
  }

  // ------------------------------------------------------------------ tags and the hover card
  const tagBox = $('.m-tags', frameEl);
  const tags = STOREYS.map((st, s) => {
    const el = document.createElement('span'); el.className = 'm-tag'; el.dataset.glass = '';
    el.innerHTML = `<i></i><b>${st.short}</b><em></em>`; tagBox.appendChild(el); glass(el);
    return el;
  });
  function paintTags() {
    tags.forEach((el, s) => {
      const st = STOREYS[s], d = slipOf(st, plan);
      el.dataset.band = plan === 'base' ? 'base' : plan === 'rec' && st.crash ? 'mark' : bandOf(d);
      el.querySelector('em').textContent = fmt(d);
      el.classList.toggle('on', s === selected || s === hovered);
    });
  }
  const card = $('.m-card', frameEl); glass(card);
  let showT = 0, hideT = 0, cardFor = -1;
  function hoverCard(s, x, y) {
    clearTimeout(showT); clearTimeout(hideT);
    if (s < 0) { hideT = setTimeout(() => { card.classList.remove('show'); cardFor = -1; }, 100); return; }
    const place = () => {
      const r = frameEl.getBoundingClientRect(), cw = card.offsetWidth || 260;
      card.style.left = `${Math.min(r.width - cw - 12, Math.max(12, x - r.left - cw / 2))}px`;
      card.style.top = `${Math.min(r.height - 150, y - r.top + 22)}px`;
    };
    if (cardFor === s) { place(); return; }
    showT = setTimeout(() => {
      const st = STOREYS[s], d = slipOf(st, plan);
      card.querySelector('[data-c=t]').textContent = st.name;
      card.querySelector('[data-c=a]').textContent = st.act;
      card.querySelector('[data-c=d]').textContent = plan === 'rec' && st.crash ? `${fmt(d)} after ${st.crash} d bought back` : `${fmt(d)} on the ${PLAN_NAME[plan].toLowerCase()}`;
      card.querySelector('[data-c=x]').textContent = st.crash ? st.action : 'No recovery needed';
      cardFor = s; place(); card.classList.add('show');
    }, cardFor >= 0 ? 0 : 300);
  }

  // ------------------------------------------------------------------ camera, drag, hover, scroll
  let yaw = 0.78, yawVel = 0, idleAt = 0, px = 0, py = 0, tx = 0, ty = 0;
  const drawerDir = new THREE.Vector3(1, 0, 1).normalize();
  const ray = new THREE.Raycaster(), ndc = new THREE.Vector2();
  let drag = null;
  canvas.style.touchAction = 'pan-y';
  function pick(e) {
    const r = canvas.getBoundingClientRect();
    ndc.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    ray.setFromCamera(ndc, camera);
    const hit = ray.intersectObjects(levels.map(L => L.hit), false)[0];
    return hit ? hit.object.userData.s : -1;
  }
  canvas.addEventListener('pointerdown', e => { drag = { x: e.clientX, y: e.clientY, moved: 0 }; canvas.setPointerCapture(e.pointerId); });
  canvas.addEventListener('pointermove', e => {
    const r = canvas.getBoundingClientRect();
    tx = (e.clientX - r.left) / r.width - 0.5; ty = (e.clientY - r.top) / r.height - 0.5;
    if (drag) {
      const dx = e.clientX - drag.x; drag.x = e.clientX; drag.moved += Math.abs(dx);
      yawVel = dx * 0.0065; yaw += yawVel; idleAt = performance.now(); canvas.classList.add('grabbing');
      hoverCard(-1);
    } else if (e.pointerType === 'mouse') {
      const s = pick(e);
      if (s !== hovered) { hovered = s; paintTags(); canvas.classList.toggle('over', s >= 0); }
      hoverCard(s, e.clientX, e.clientY);
    }
    wake();
  });
  const end = e => {
    if (drag && drag.moved < 6) { const s = pick(e); if (s >= 0) select(s); else if (selected >= 0) select(selected); }
    drag = null; canvas.classList.remove('grabbing');
  };
  canvas.addEventListener('pointerup', end);
  canvas.addEventListener('pointercancel', () => { drag = null; canvas.classList.remove('grabbing'); });
  canvas.addEventListener('pointerleave', () => { if (!drag) { hovered = -1; paintTags(); canvas.classList.remove('over'); hoverCard(-1); } tx = ty = 0; });

  function resize() {
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h, false); camera.aspect = w / h;
    camera.zoom = w / h < 0.9 ? 0.6 : 0.8;
    camera.updateProjectionMatrix(); wake();
  }
  new ResizeObserver(resize).observe(canvas);

  const v = new THREE.Vector3(), target = new THREE.Vector3();
  const ease = t => t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
  function explodeAmount() {
    if (REDUCED) return 1;
    const r = section.getBoundingClientRect(), vh = innerHeight;
    const p = (vh - r.top) / (vh + r.height * 0.4);            // 0 as the section enters, 1 most of the way through
    return ease(Math.min(1, Math.max(0, (p - 0.18) / 0.5)));
  }

  let raf = 0, visible = false, last = performance.now(), settle = 0;
  function frame(now) {
    raf = 0;
    const dt = Math.min(0.05, (now - last) / 1000); last = now;
    const k = REDUCED ? 1 : 1 - Math.pow(0.0015, dt);           // frame-rate independent approach
    const gap = 2.6 * explodeAmount();
    let busy = false;
    levels.forEach((L, s) => {
      const lift = s === selected ? 1.4 : 0, slide = s === selected ? 1 : 0, glow = s === hovered && s !== selected ? 1 : 0;
      L.lift += (lift - L.lift) * k; L.slide += (slide - L.slide) * k; L.glow += (glow - L.glow) * k;
      L.cur.lerp(L.goal, k);
      if (Math.abs(lift - L.lift) + Math.abs(slide - L.slide) + Math.abs(glow - L.glow) > 0.002) busy = true;
      const y = 0.6 + s * (SH + gap) - 0.6 + L.lift;
      L.g.position.set(drawerDir.x * 8 * L.slide, y, drawerDir.z * 8 * L.slide);
      L.mats[1].color.copy(L.cur);
      L.mats[0].color.copy(BASE).lerp(L.cur, 0.45);                 // the frame keeps most of its concrete, the slab carries the band
      L.mats.forEach(m => m.emissive.setRGB(0.16 * L.glow, 0.15 * L.glow, 0.12 * L.glow));
    });
    // camera: an idle drift across the front corner until someone drags, then inertia
    if (!drag) { yaw += yawVel; yawVel *= Math.pow(0.04, dt); }
    if (!REDUCED && !drag && now - idleAt > 3500) yaw += dt * 0.07;
    px += (tx - px) * Math.min(1, dt * 3); py += (ty - py) * Math.min(1, dt * 3);
    const top = NS * SH + (NS - 1) * gap;
    target.set(0, top * 0.46, 0);
    const dist = 70 + gap * 6;
    camera.position.set(Math.cos(yaw + px * 0.12) * dist, top * 0.46 + 24 - py * 6, Math.sin(yaw + px * 0.12) * dist);
    camera.lookAt(target);
    renderer.render(scene, camera);

    // tags follow the front corner of each slab
    const r = canvas.getBoundingClientRect();
    const cornerX = Math.cos(yaw) > 0 ? W / 2 : -W / 2, cornerZ = Math.sin(yaw) > 0 ? D / 2 : -D / 2;
    levels.forEach((L, s) => {
      v.set(cornerX, 0.6 + CH + SLAB, cornerZ).add(L.g.position).project(camera);
      tags[s].style.transform = `translate(${(v.x * 0.5 + 0.5) * r.width + 10}px, ${(-v.y * 0.5 + 0.5) * r.height - 14}px)`;
    });

    const moving = !REDUCED || busy || Math.abs(yawVel) > 1e-4 || drag;
    if (busy || Math.abs(yawVel) > 1e-4) settle = 30; else settle = Math.max(0, settle - 1);
    if (visible && !document.hidden && (moving || settle > 0)) raf = requestAnimationFrame(frame);
  }
  function wake() { if (!raf && visible && !document.hidden) { last = performance.now(); raf = requestAnimationFrame(frame); } }
  new IntersectionObserver(([e]) => { visible = e.isIntersecting; if (visible) wake(); }, { rootMargin: '120px 0px' }).observe(canvas);
  addEventListener('scroll', () => { if (REDUCED) return; wake(); }, { passive: true });
  document.addEventListener('visibilitychange', wake);

  resize(); setPlan('fore');
}

storeyExplorer();
