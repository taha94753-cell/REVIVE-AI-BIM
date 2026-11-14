// REVIVE landing page.
//  * the film: one tower (Three.js), pinned full screen and built by the scroll from frame to handover: the frame rises
//    under a tower crane, a scan recolours it by delay risk, the recovery pulses pink, then limestone, glazing lit from
//    inside, roof and landscaping. Five chapters morph through it, changing sides each time, and the camera leans
//    away from the side the text is on
//  * real figures come from /api/public/overview (cross-validated model card), never hard-coded
//  * motion: Motion (vendored) for the scroll, tabs and reveals; view transitions morph the tab panels
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

// =================================================================== 3D site: one tower, frame to handover
// A 3 x 2 bay, ten-storey tower goes through a real sequence; the scroll sets where in it we are (u, in seconds of T):
//   frame      columns, beams and slabs storey by storey under a working tower crane
//   scan       a scan plane sweeps up and tints each storey by delay risk; the late storeys pulse pink (recovery)
//   envelope   slim limestone piers and spandrels, then full bay glazing with bronze mullions, storey by storey
//   roof       parapet, plant room and rooftop units
//   handover   the crane is dismantled, paving, canopy and trees go in, and the lanterns come on
// Every member is an instance with its own storey and trade, so each one is placed, not faded in.
const T = { frame: [0.4, 7.4], scan: [7.6, 10.2], rec: [10.2, 12.4], env: [12.2, 19.6], roof: [19.2, 21], out: [20.6, 23.4] };
// film progress (0..1) -> u: one chapter per phase, so each chapter's words sit over the work they describe
const KEYS = [[0, 3.6], [0.2, 7.5], [0.4, 10.3], [0.6, 12.8], [0.8, 19.4], [0.96, 24], [1, 24]];
const uAt = k => { for (let i = 1; i < KEYS.length; i++) if (k <= KEYS[i][0]) { const [a, ua] = KEYS[i - 1], [b, ub] = KEYS[i]; return ua + (ub - ua) * (k - a) / (b - a); } return 24; };
let filmK = 0, filmSide = -1;          // set by the scroll; -1 = text on the left, so the building leans right
const span = (u, [a, b]) => Math.min(1, Math.max(0, (u - a) / (b - a)));

function siteModel() {
  const canvas = $('#scene');
  let renderer;
  try { renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: 'high-performance' }); }
  catch { canvas.hidden = true; return null; }
  renderer.setPixelRatio(Math.min(devicePixelRatio, 1.75));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.18;
  renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x131209);          // the page's own ground: the site fades into it
  scene.fog = new THREE.Fog(0x131209, 90, 240);
  const camera = new THREE.PerspectiveCamera(34, 1, 0.1, 500);
  const target = new THREE.Vector3(0, 8, 0);

  // a sky to reflect: glazing and aluminium need something to mirror or they read as flat paint
  const sky = document.createElement('canvas'); sky.width = 16; sky.height = 256;
  const sg = sky.getContext('2d'), grad = sg.createLinearGradient(0, 0, 0, 256);
  grad.addColorStop(0, '#232833'); grad.addColorStop(0.44, '#F0D9B5'); grad.addColorStop(0.5, '#7A6A55'); grad.addColorStop(1, '#15140F');
  sg.fillStyle = grad; sg.fillRect(0, 0, 16, 256);
  const skyTex = new THREE.CanvasTexture(sky); skyTex.mapping = THREE.EquirectangularReflectionMapping; skyTex.colorSpace = THREE.SRGBColorSpace;
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromEquirectangular(skyTex).texture;

  scene.add(new THREE.HemisphereLight(0xC4D0E6, 0x2A241C, 0.95));
  const rim = new THREE.DirectionalLight(0x9FC0FF, 1.5); rim.position.set(-60, 8, -50); scene.add(rim);   // a cool rim so the form reads
  const sun = new THREE.DirectionalLight(0xFFD9AE, 3.2);
  sun.castShadow = true; sun.shadow.mapSize.set(2048, 2048); sun.shadow.bias = -0.0004; sun.shadow.normalBias = 0.02;
  Object.assign(sun.shadow.camera, { left: -42, right: 42, top: 42, bottom: -42, near: 1, far: 200 });
  scene.add(sun, sun.target);

  // glazing reads as glass when it carries the sky: light at the head of each pane, darker at the sill, one soft streak
  function glazing() {
    const c = document.createElement('canvas'); c.width = 64; c.height = 128;
    const g = c.getContext('2d'), lg = g.createLinearGradient(0, 0, 0, 128);
    lg.addColorStop(0, '#B4C6D3'); lg.addColorStop(0.45, '#7F97A9'); lg.addColorStop(1, '#4A5F70');
    g.fillStyle = lg; g.fillRect(0, 0, 64, 128);
    g.fillStyle = 'rgba(255,255,255,0.16)'; g.beginPath(); g.moveTo(10, 128); g.lineTo(34, 128); g.lineTo(58, 0); g.lineTo(34, 0); g.fill();
    const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
  }
  // ---- materials: what the block is actually made of
  const std = (color, rough, metal = 0, extra = {}) => new THREE.MeshStandardMaterial({ color, roughness: rough, metalness: metal, ...extra });
  const matte = color => new THREE.MeshLambertMaterial({ color });        // the ground takes no highlight from the rim light
  const MAT = {
    ground: matte(0x15140F), grass: matte(0x1A1D14), paving: std(0x7A7368, 0.9), road: matte(0x1B1B1B), kerb: std(0x8A8377, 0.9),
    frame: std(0xBDB6AA, 0.88),                                   // in-situ concrete
    slab: std(0xC6BEB0, 0.9),
    precast: std(0xF1E9DC, 0.72),                                 // pale limestone piers and spandrels
    spandrel: std(0xE6DCCB, 0.75),
    glass: std(0xFFFFFF, 0.12, 0.25, { map: glazing(), envMapIntensity: 0.9, emissive: 0xFFA24A, emissiveIntensity: 0 }),   // glazing; lit from inside at dusk
    alu: std(0x4A3B2E, 0.35, 0.8),                                // bronze mullions and coping
    plant: std(0xA2A7AC, 0.55, 0.4), louvre: std(0x7D838A, 0.5, 0.5),
    trunk: std(0x6B5A48, 0.9), leaf: std(0x6F8A58, 0.95, 0, { flatShading: true }), leaf2: std(0x5E7A4D, 0.95, 0, { flatShading: true }),
  };

  // ---- site: ground, paving apron, a road along one side, grass beyond
  const plane = (w, d, mat, y, x = 0, z = 0) => {
    const m = new THREE.Mesh(new THREE.PlaneGeometry(w, d), mat); m.rotation.x = -Math.PI / 2; m.position.set(x, y, z); m.receiveShadow = true; scene.add(m); return m;
  };
  plane(600, 600, MAT.ground, -0.02);
  plane(120, 90, MAT.grass, -0.01);
  plane(40, 32, MAT.paving, 0.005);
  plane(9, 140, MAT.road, 0.008, 28.5, 0);
  const grid = new THREE.GridHelper(40, 20, 0x8A8377, 0x5E584F);       // setting-out grid on the apron, gone at handover
  grid.material.transparent = true; grid.material.opacity = 0.5; grid.position.y = 0.02; scene.add(grid);

  // ---- every placed member is an instance with a storey, a trade and its resting transform
  const BX = 3, BZ = 2, SP = 6, SH = 3.6, NS = 10, HX = (BX * SP) / 2, HZ = (BZ * SP) / 2;
  const kinds = {};
  const items = [];
  const box = (w, h, d) => new THREE.BoxGeometry(w, h, d);
  function kind(name, geo, mat, count, { shadow = true, colour = false } = {}) {
    const m = new THREE.InstancedMesh(geo, mat, count);
    m.instanceMatrix.setUsage(THREE.DynamicDrawUsage); m.castShadow = shadow; m.receiveShadow = true; m.count = 0;
    if (colour) m.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(count * 3).fill(1), 3);
    m.userData.h = geo.parameters?.height ?? 1;
    scene.add(m); kinds[name] = m; return m;
  }
  const put = (name, s, x, y, z, ry = 0, grow = 'up') => {
    const m = kinds[name]; items.push({ m, i: m.count++, s, x, y, z, ry, grow, name });
  };

  // frame: columns, beams both ways, floor slabs (recoloured by the risk scan, so they carry instance colours)
  kind('col', box(0.6, SH, 0.6), MAT.frame, (BX + 1) * (BZ + 1) * NS, { colour: true });
  kind('bx', box(SP, 0.55, 0.4), MAT.frame, BX * (BZ + 1) * NS, { colour: true });
  kind('bz', box(0.4, 0.55, SP), MAT.frame, (BX + 1) * BZ * NS, { colour: true });
  kind('slab', box(BX * SP + 0.6, 0.3, BZ * SP + 0.6), MAT.slab, NS, { colour: true });
  for (let s = 0; s < NS; s++) {
    const y0 = s * SH;
    for (let i = 0; i <= BX; i++) for (let k = 0; k <= BZ; k++) put('col', s, -HX + i * SP, y0 + SH / 2, -HZ + k * SP);
    for (let i = 0; i < BX; i++) for (let k = 0; k <= BZ; k++) put('bx', s, -HX + (i + 0.5) * SP, y0 + SH - 0.3, -HZ + k * SP, 0, 'drop');
    for (let i = 0; i <= BX; i++) for (let k = 0; k < BZ; k++) put('bz', s, -HX + i * SP, y0 + SH - 0.3, -HZ + (k + 0.5) * SP, 0, 'drop');
    put('slab', s, 0, y0 + SH - 0.0, 0, 0, 'drop');
  }

  // envelope: on each face, a pilaster at every column line, a spandrel over every slab edge, and in every bay
  // a glazed panel with three mullions; the ground storey is a full-height glazed lobby
  const faces = [];                                      // [axis length, bays, normal x, normal z]
  for (const [nx, nz] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) faces.push({ nx, nz, bays: nx ? BZ : BX, half: nx ? HZ : HX, out: (nx ? HX : HZ) + 0.32 });
  const per = faces.reduce((a, f) => a + f.bays, 0), lines = faces.reduce((a, f) => a + f.bays + 1, 0);
  kind('pil', box(0.45, SH, 0.5), MAT.precast, lines * NS);
  kind('spd', box(SP - 0.45, 0.7, 0.42), MAT.spandrel, per * NS);
  kind('gls', box(SP - 0.45, 1, 0.08), MAT.glass, per * NS, { shadow: false });
  kind('mul', box(0.09, 1, 0.16), MAT.alu, per * NS * 3);
  const along = (f, u) => f.nx ? [f.nx * f.out, u] : [u, f.nz * f.out];
  for (let s = 0; s < NS; s++) {
    const y0 = s * SH, winB = s === 0 ? 0.05 : y0 + 0.25, winT = y0 + SH - 0.45, winH = winT - winB;
    for (const f of faces) {
      const ry = f.nx ? Math.PI / 2 : 0;
      for (let b = 0; b <= f.bays; b++) { const [x, z] = along(f, -f.half + b * SP); put('pil', s, x, y0 + SH / 2, z, ry, 'up'); }
      for (let b = 0; b < f.bays; b++) {
        const u = -f.half + (b + 0.5) * SP;
        const [x, z] = along(f, u);
        put('spd', s, x, y0 + SH - 0.1, z, ry, 'lift');
        const [gx, gz] = along({ ...f, out: f.out - 0.18 }, u);
        items.push({ m: kinds.gls, i: kinds.gls.count++, s, x: gx, y: winB + winH / 2, z: gz, ry, grow: 'lift', sy: winH, name: 'gls' });
        for (const k of [-1, 0, 1]) {
          const [mx, mz] = along({ ...f, out: f.out - 0.12 }, u + k * (SP - 0.45) / 4);
          items.push({ m: kinds.mul, i: kinds.mul.count++, s, x: mx, y: winB + winH / 2, z: mz, ry, grow: 'lift', sy: winH, name: 'mul' });
        }
      }
    }
  }

  // roof: parapet with an aluminium coping, a plant room with louvres, four condensers
  const roofY = NS * SH + 0.15;
  kind('par', box(1, 1, 1), MAT.precast, 4);
  kind('cop', box(1, 1, 1), MAT.alu, 4);
  [[0, HZ + 0.32, 2 * HX + 1.4, 0.4], [0, -HZ - 0.32, 2 * HX + 1.4, 0.4], [HX + 0.32, 0, 0.4, 2 * HZ + 0.6], [-HX - 0.32, 0, 0.4, 2 * HZ + 0.6]].forEach(([x, z, w, d]) => {
    items.push({ m: kinds.par, i: kinds.par.count++, s: NS, x, y: roofY + 0.55, z, sx: w, sy: 1.1, sz: d, grow: 'up', name: 'par' });
    items.push({ m: kinds.cop, i: kinds.cop.count++, s: NS, x, y: roofY + 1.16, z, sx: w + 0.1, sy: 0.12, sz: d + 0.14, grow: 'drop', name: 'cop' });
  });
  kind('plant', box(1, 1, 1), MAT.plant, 1);
  items.push({ m: kinds.plant, i: kinds.plant.count++, s: NS, x: -3, y: roofY + 1.6, z: -1, sx: 8, sy: 3.2, sz: 6, grow: 'up', name: 'plant' });
  kind('louv', box(1, 1, 1), MAT.louvre, 2);
  items.push({ m: kinds.louv, i: kinds.louv.count++, s: NS, x: -3, y: roofY + 1.7, z: 2.03, sx: 6.4, sy: 1.6, sz: 0.08, grow: 'up', name: 'louv' });
  items.push({ m: kinds.louv, i: kinds.louv.count++, s: NS, x: 1.03, y: roofY + 1.7, z: -1, sx: 0.08, sy: 1.6, sz: 4.4, grow: 'up', name: 'louv' });
  kind('ac', box(1.6, 1.1, 1.6), MAT.plant, 4);
  [[5, -4], [7.4, -4], [5, -1.4], [7.4, -1.4]].forEach(([x, z]) => put('ac', NS, x, roofY + 0.55, z, 0, 'drop'));

  // handover: an entrance canopy on two posts, a kerb line and trees along the street and the front
  kind('can', box(1, 1, 1), std(0x9AA0A6, 0.4, 0.6), 1);
  items.push({ m: kinds.can, i: kinds.can.count++, s: NS + 1, x: 0, y: 3.4, z: HZ + 2.2, sx: 9, sy: 0.3, sz: 3.6, grow: 'drop', name: 'can' });
  kind('post', new THREE.CylinderGeometry(0.1, 0.1, 3.4, 10), MAT.alu, 2);
  [-4.2, 4.2].forEach(x => put('post', NS + 1, x, 1.7, HZ + 3.8, 0, 'up'));
  kind('kerb', box(1, 1, 1), MAT.kerb, 1);
  items.push({ m: kinds.kerb, i: kinds.kerb.count++, s: NS + 1, x: 20.9, y: 0.12, z: 0, sx: 0.3, sy: 0.24, sz: 70, grow: 'up', name: 'kerb' });
  const treeSpots = [];
  for (let z = -15; z <= 15; z += 6) treeSpots.push([19, z]);
  for (let x = -14; x <= 14; x += 7) if (Math.abs(x) > 5) treeSpots.push([x, 15]);
  kind('trunk', new THREE.CylinderGeometry(0.16, 0.22, 2.6, 8), MAT.trunk, treeSpots.length);
  kind('crown', new THREE.IcosahedronGeometry(1.9, 1), MAT.leaf, treeSpots.length);
  treeSpots.forEach(([x, z], n) => {
    put('trunk', NS + 1, x, 1.3, z, 0, 'up');
    items.push({ m: kinds.crown, i: kinds.crown.count++, s: NS + 1, x, y: 3.9 + (n % 3) * 0.25, z, ry: n, sx: 1 + (n % 2) * 0.15, sy: 1.1, sz: 1, grow: 'tree', name: 'crown', lag: n * 0.04 });
  });
  Object.values(kinds).forEach(m => { m.instanceMatrix.needsUpdate = true; });

  // ---- tower crane in steel linework; it is dismantled at handover
  const crane = new THREE.Group(); crane.position.set(-HX - 7, 0, -HZ - 5); scene.add(crane);
  const craneMats = [];
  const line = (geo, c = 0x2A2D31, o = 0.9) => { const mat = new THREE.LineBasicMaterial({ color: c, transparent: true, opacity: o }); craneMats.push([mat, o]); return new THREE.LineSegments(new THREE.EdgesGeometry(geo), mat); };
  const H = NS * SH + 8;
  for (let y = 0; y < H; y += 2) { const seg = line(box(1.2, 2, 1.2)); seg.position.y = y + 1; crane.add(seg); }
  const slew = new THREE.Group(); slew.position.y = H; crane.add(slew);
  const jib = line(box(32, 1, 1)); jib.position.x = 15; slew.add(jib);
  const cjib = line(box(10, 1, 1)); cjib.position.x = -6; slew.add(cjib);
  const cab = new THREE.Mesh(box(1.6, 1.4, 1.6), std(0xFFC21A, 0.6)); cab.position.set(0, -1, 0.4); cab.castShadow = true; slew.add(cab);
  const weight = new THREE.Mesh(box(2.4, 1.6, 1.4), MAT.frame); weight.position.set(-9.5, -0.6, 0); weight.castShadow = true; slew.add(weight);
  const trolley = new THREE.Group(); slew.add(trolley);
  const cableGeo = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3(0, -10, 0)]);
  const cableMat = new THREE.LineBasicMaterial({ color: 0x2A2D31, transparent: true, opacity: 0.7 }); craneMats.push([cableMat, 0.7]);
  trolley.add(new THREE.Line(cableGeo, cableMat));
  const hook = new THREE.Mesh(box(0.7, 0.7, 0.7), MAT.alu); trolley.add(hook);

  // ---- scan plane for the risk check
  const scan = new THREE.Mesh(new THREE.PlaneGeometry(BX * SP + 8, BZ * SP + 8), new THREE.MeshBasicMaterial({ color: 0x1F5FAD, transparent: true, opacity: 0, side: THREE.DoubleSide, depthWrite: false }));
  scan.rotation.x = -Math.PI / 2; scene.add(scan);
  const scanEdge = new THREE.LineSegments(new THREE.EdgesGeometry(scan.geometry), new THREE.LineBasicMaterial({ color: 0x1F5FAD, transparent: true, opacity: 0 }));
  scan.add(scanEdge);

  const C = { built: new THREE.Color(1, 1, 1), go: new THREE.Color(0x22B07A), watch: new THREE.Color(0xF2C230), risk: new THREE.Color(0xF07A2A),
    crit: new THREE.Color(0xE03A50), mark: new THREE.Color(0xFF79C6), active: new THREE.Color(0xFFC21A), done: new THREE.Color(0xD9D6D0) };
  const riskOf = s => [C.done, C.done, C.go, C.watch, C.risk, C.crit][Math.floor(s / NS * 6)];   // the higher storeys run later
  const crashed = { has: s => s >= NS - 3 };

  const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), v = new THREE.Vector3(), sc = new THREE.Vector3(), col = new THREE.Color(), Y = new THREE.Vector3(0, 1, 0);
  const ease = t => 1 - Math.pow(1 - Math.min(1, Math.max(0, t)), 3);
  const ENV = new Set(['pil', 'spd', 'gls', 'mul']);
  const ENV_LAG = { pil: 0, spd: 0.25, gls: 0.55, mul: 0.7 };

  /** How far one member is through its own placement (0 = not yet, 1 = in place), from the loop time u. */
  function progress(it, u) {
    if (it.s >= NS) {                                     // roof, then the handover works
      const p = it.s === NS ? span(u, T.roof) : span(u, T.out);
      return ease(p * 1.6 - (it.lag || 0) - (it.name === 'cop' || it.name === 'louv' ? 0.4 : 0));
    }
    if (ENV.has(it.name)) return ease((span(u, T.env) * (NS + 0.6) - it.s) * 1.5 - ENV_LAG[it.name]);
    const b = span(u, T.frame) * (NS + 0.7) - it.s;
    return ease(b * (it.name === 'col' ? 1.7 : 1.3) - (it.name === 'col' ? 0 : it.name === 'slab' ? 0.75 : 0.4));
  }

  function frame(u, t) {
    const fade = 1;
    const scanP = span(u, T.scan), recP = span(u, T.rec), outP = span(u, T.out);
    const restore = ease(span(u, [T.rec[1], T.rec[1] + 1.4]));   // recovery bought: the risk tint leaves the frame
    for (const it of items) {
      const g = progress(it, u) * fade, e = Math.max(0.001, g);
      const bx = it.sx || 1, by = it.sy || 1, bz = it.sz || 1;
      q.setFromAxisAngle(Y, it.ry || 0);
      if (it.grow === 'up') { sc.set(bx, by * e, bz); v.set(it.x, it.y - it.m.userData.h * by * (1 - e) / 2, it.z); }   // rises from its base
      else if (it.grow === 'drop') { sc.set(bx * e, by, bz * e); v.set(it.x, it.y + (1 - g) * 2.2, it.z); }
      else if (it.grow === 'lift') { sc.set(bx * Math.min(1, e * 1.05), by * e, bz); v.set(it.x, it.y + (1 - g) * 1.6, it.z); }
      else { sc.set(bx * e, by * e, bz * e); v.set(it.x, it.y, it.z); }        // trees grow in place
      m4.compose(v, q, sc); it.m.setMatrixAt(it.i, m4);
      if (it.m.instanceColor && it.s < NS) {
        const placing = g > 0.02 && g < 0.98 && u < T.frame[1] + 0.3;
        const scanned = scanP > 0 && scanP * NS * 1.05 > it.s;
        if (placing) col.copy(C.active); else col.copy(C.built);
        if (scanned) col.lerp(riskOf(it.s), 0.85 * (1 - restore));
        if (recP > 0 && crashed.has(it.s) && restore < 1) col.lerp(C.mark, (0.86 + 0.14 * Math.sin(t * 6)) * (1 - restore));
        it.m.setColorAt(it.i, col);
      }
    }
    Object.values(kinds).forEach(m => { m.instanceMatrix.needsUpdate = true; if (m.instanceColor) m.instanceColor.needsUpdate = true; });

    const sp = scanP;
    scan.position.y = sp * NS * SH + 0.4;
    const scanOn = scanP > 0 && scanP < 1;
    scan.material.opacity = scanOn ? 0.16 : 0; scanEdge.material.opacity = scanOn ? 0.9 : 0;
    grid.material.opacity = 0.5 * (1 - outP);

    // the crane works through the frame and envelope, then is taken down: jib folds away, mast sinks, lines fade
    const working = 1 - outP;
    slew.rotation.y = -0.6 + Math.sin(t * 0.22) * 0.55;
    trolley.position.x = 10 + (Math.sin(t * 0.5) * 0.5 + 0.5) * 18;
    const drop = 6 + (Math.sin(t * 0.8) * 0.5 + 0.5) * 14;
    hook.position.y = -drop; cableGeo.attributes.position.setY(1, -drop); cableGeo.attributes.position.needsUpdate = true;
    crane.position.y = -H * ease(outP * 1.2 - 0.2) * 1.02;
    craneMats.forEach(([mat, o]) => { mat.opacity = o * working; });
    crane.visible = working > 0.01 && fade > 0.02;
    // the sun sinks as the work goes on, so the shadows lengthen; the glazing lights up storey by storey at handover
    const sa = 0.9 + u * 0.018;
    sun.position.set(Math.cos(sa) * 70, 62 - u * 1.2, Math.sin(sa) * 70 - 20); sun.target.position.set(0, 0, 0);
    sun.intensity = 3.2 - span(u, [14, 24]) * 1.4;
    MAT.glass.emissiveIntensity = 0.1 + ease(span(u, [16, 23.6])) * 1.5;
    target.y = 7 + ease(span(u, T.frame)) * 10;                            // the view rises with the frame
  }

  let px = 0, py = 0, tx = 0, ty = 0, ox = -0.12, uCur = 0, W = 1, Hh = 1;
  addEventListener('pointermove', e => { tx = (e.clientX / innerWidth - 0.5); ty = (e.clientY / innerHeight - 0.5); }, { passive: true });
  function resize() {
    W = canvas.clientWidth || innerWidth; Hh = canvas.clientHeight || innerHeight;
    renderer.setSize(W, Hh, false); camera.aspect = W / Hh;
    camera.zoom = W / Hh < 0.9 ? 0.6 : 1;                                   // narrow screens pull back further
    camera.updateProjectionMatrix();
  }
  new ResizeObserver(resize).observe(canvas); resize();
  const canRun = () => !REDUCED;
  let visible = true, raf = 0, t0 = performance.now(), tLast = 0;
  new IntersectionObserver(([e]) => { visible = e.isIntersecting; if (visible && !raf && canRun()) loop(); }).observe(canvas);
  function place(u) {
    px += (tx - px) * 0.04; py += (ty - py) * 0.04;
    ox += ((W / Hh < 0.9 ? 0 : filmSide * (0.27 + u * 0.003)) - ox) * 0.05;          // lean away from the chapter's text
    camera.setViewOffset(W, Hh, ox * W, -Hh * 0.04, W, Hh);
    const a = 0.42 + u * 0.036 + px * 0.25, r = 92 - u * 0.5;          // the camera walks round the front corner as the work goes on
    camera.position.set(Math.cos(a) * r, 9 + u * 0.3 + py * -4, Math.sin(a) * r);           // a low viewpoint: the tower stands over you
    camera.lookAt(target);
  }
  function loop() {
    raf = 0;
    if (!visible || document.hidden) return;
    const t = (performance.now() - t0) / 1000, dt = Math.min(0.5, t - tLast); tLast = t;
    uCur += (uAt(filmK) - uCur) * (1 - Math.exp(-dt * 3.5));             // an inertial scrub, the same on slow machines
    frame(uCur, t); place(uCur); renderer.render(scene, camera);
    raf = requestAnimationFrame(loop);
  }
  document.addEventListener('visibilitychange', () => { if (!document.hidden && visible && !raf && canRun()) loop(); });
  if (REDUCED) { frame(24, 0); place(24); renderer.render(scene, camera); }  // reduced motion: the finished building, still
  else loop();
  return { frame, place, render: () => renderer.render(scene, camera) };
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
    $('[data-fill=base]').textContent = g.baseline_mae != null ? g.baseline_mae.toFixed(1) : 'n/a';
    $('[data-fill=real]').textContent = d.projects;
    $('#numbers-note').textContent = `Figures come from the trained model card. The survey holds ${d.records ?? d.projects} records, ${d.hypothetical || 0} of them augmented (scenario rows, not verified projects, labelled wherever they appear). They help train the model; every score is measured on the ${d.projects} real completed projects only.`;
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

// =================================================================== tabbed walkthrough
const ORDER = ['now', 'next', 'why', 'fix', 'live'];
const AUTO_S = 7;            // seconds per question while nobody is interacting
let cur = 'now', prog = null, paused = false, loops = [];

/** Each panel's diagram builds itself the way the analysis does: curves draw, bars grow, the optimum lands. */
function playPanel(x) {
  loops.forEach(l => l.stop()); loops = [];
  if (!M || REDUCED) return;
  const p = $(`#xp-${x}`), A = M.animate, S = M.stagger;
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
  if (M && !REDUCED && dir) M.animate($('.xt-ind'), { scaleX: [1, 1.16, 0.93, 1.03, 1], scaleY: [1, 0.82, 1.07, 0.98, 1] }, { duration: 0.75, ease: 'easeOut' });   // the lens squeezes, lands, wobbles
  const swap = () => { $$('.xpanel').forEach(p => { p.hidden = p.dataset.x !== x; }); playPanel(x); };
  if (dir && !REDUCED && document.startViewTransition) document.startViewTransition(swap); else swap();   // one answer morphs into the next
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

// =================================================================== scroll: the film, the tagline and the reveals
function scrollMotion() {
  const nav = $('#nav');
  $('#nav-toggle').addEventListener('click', e => e.currentTarget.setAttribute('aria-expanded', nav.classList.toggle('open')));
  $('#nav-links').addEventListener('click', () => { nav.classList.remove('open'); $('#nav-toggle').setAttribute('aria-expanded', 'false'); });
  if (!M || REDUCED) return;
  M.inView('.reveal-up', el => { M.animate(el, { opacity: [0, 1], y: [32, 0] }, { duration: 0.7, ease: OUT }); }, { margin: '0px 0px -10% 0px' });
  // five chapters morph into each other in place while the film holds: each sharpens and settles, then dissolves
  const chaps = $$('.chap'), n = chaps.length;
  M.scroll(k => {
    filmK = k;
    filmSide = chaps[Math.min(n - 1, Math.floor(k * n))].classList.contains('right') ? 1 : -1;
    chaps.forEach((c, i) => {
      const l = k * n - i, fin = i === 0 ? 1 : Math.min(1, Math.max(0, (l + 0.1) / 0.22)), fout = i === n - 1 ? 1 : Math.min(1, Math.max(0, (0.9 - l) / 0.22));
      const o = Math.min(fin, fout);
      c.style.opacity = o; c.style.transform = `scale(${fin < 1 ? 0.94 + 0.06 * o : 1.06 - 0.06 * o})`; c.style.filter = o < 1 ? `blur(${(1 - o) * 12}px)` : '';
      c.style.visibility = o ? '' : 'hidden';
    });
  }, { target: $('.film'), offset: ['start start', 'end end'] });
  // the tagline: each word lights as it crosses the trigger line, in reading order
  const tag = $('#tagline');
  tag.innerHTML = tag.textContent.split(' ').map(w => `<span>${w}</span>`).join(' ');
  const words = $$('span', tag);
  M.scroll(k => words.forEach((w, i) => w.classList.toggle('on', i < k * (words.length + 1))), { target: tag, offset: ['start 0.85', 'end 0.4'] });
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
wireAuth();
plate($('.xt-ind'), $('#xt-now'), { instant: true });
wireTabs();
overview();
scrollMotion();
