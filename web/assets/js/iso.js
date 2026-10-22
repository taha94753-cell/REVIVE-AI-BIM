// Isometric site models for the "For companies" points: each point is a small CSS-3D model on a concrete plinth
// instead of an icon card. No library and no canvas: every block is a div with three faces (top, +x, +y) inside a
// preserve-3d stage turned to the isometric view (rotateX(60deg) rotateZ(45deg)), so the models stay sharp at any
// size, work offline and tilt in real depth under the pointer (tilt.js, the "3D card" pattern).
//  * a model assembles floor by floor the first time it scrolls into view (.built on the stage), then runs a
//    short idle loop of its own (CSS keyframes on .lp-* blocks)
//  * under prefers-reduced-motion the finished model shows at once and nothing loops
import { REDUCED } from './tabs.js';

// [colour, x, y, z, w, d, h, loop class]. Units are px on a 180 x 180 plinth; z is height above the plinth.
const FLOOR = 15;
const floors = (x, y, w, n, c, top = '') =>
  Array.from({ length: n }, (_, i) => [c, x, y, i * FLOOR, w, w, FLOOR - 2, i === n - 1 ? top : '']);

const SCENES = {
  // three companies, three buildings: each its own pad, its own height
  workspaces: [
    ['pad', 10, 118, 0, 52, 52, 2], ['pad', 64, 64, 0, 52, 52, 2], ['pad', 118, 10, 0, 52, 52, 2],
    ...floors(14, 122, 44, 2, 'con', 'lp-lift'),
    ...floors(68, 68, 44, 5, 'sig', 'lp-lift d2'),
    ...floors(122, 14, 44, 3, 'ink', 'lp-lift d3'),
  ],
  // one company's building inside its enclosure; a probe from outside stops at the wall
  isolated: [
    ...floors(66, 66, 48, 3, 'ink'),
    ['glass', 38, 38, 0, 104, 104, 64],
    ['sig', 160, 81, 0, 18, 18, 18, 'lp-probe'],
  ],
  // admins hold the tall column; members work on the shorter ones
  roles: [
    ...floors(34, 34, 34, 4, 'sig', 'lp-lift'),
    ...floors(96, 30, 26, 2, 'con'),
    ...floors(30, 96, 26, 2, 'con'),
    ...floors(96, 96, 26, 2, 'ink'),
  ],
  // a phone on site sends to the office; the token travels the link
  links: [
    ['ink', 18, 128, 0, 44, 10, 70],
    ...floors(104, 22, 56, 3, 'con'),
    ['sig', 34, 116, 0, 14, 14, 14, 'lp-token'],
  ],
  // the core inside nested shells, a scan plane passing through them
  hardened: [
    ['sig', 70, 70, 0, 40, 40, 40],
    ['glass', 50, 50, 0, 80, 80, 62],
    ['glass', 26, 26, 0, 128, 128, 70],
    ['scan', 26, 26, 0, 128, 128, 1, 'lp-scan'],
  ],
  // a rack in the site office: no line out
  offline: [
    ['ink', 50, 64, 0, 76, 52, 15, 'rk'],
    ['ink', 50, 64, 17, 76, 52, 15, 'rk d2'],
    ['ink', 50, 64, 34, 76, 52, 15, 'rk d3'],
    ['con', 136, 30, 0, 28, 28, 28],
  ],
};

function block([c, x, y, z, w, d, h, loop = ''], i) {
  const b = document.createElement('i');
  b.className = `bx ${c}`;
  b.style.cssText = `--x:${x}px;--y:${y}px;--z:${z}px;--w:${w}px;--d:${d}px;--h:${h}px;--i:${i}`;
  const m = document.createElement('b');            // the moving part: drops in, then loops
  m.className = `bm ${loop}`.trim();
  // glass shows its far walls too, so the enclosure reads as a closed box
  m.innerHTML = '<s class="ft"></s><s class="fx"></s><s class="fy"></s>' + (c === 'glass' ? '<s class="fbx"></s><s class="fby"></s>' : '');
  b.append(m);
  return b;
}

function build(stage) {
  const parts = SCENES[stage.dataset.iso];
  if (!parts) return;
  const world = document.createElement('div');
  world.className = 'iso-world';
  const plinth = block(['plinth', 0, 0, -10, 180, 180, 10], 0);
  world.append(plinth, ...parts.map((p, i) => block(p, i + 1)));
  stage.append(world);
}

/** Build every [data-iso] stage under root; each assembles when it first scrolls into view. */
export function isoScenes(root = document) {
  const stages = [...root.querySelectorAll('[data-iso]')];
  stages.forEach(build);
  if (REDUCED || !('IntersectionObserver' in window)) { stages.forEach(s => s.classList.add('built', 'still')); return; }
  const io = new IntersectionObserver(es => es.forEach(e => {
    if (!e.isIntersecting) return;
    e.target.classList.add('built');
    io.unobserve(e.target);
  }), { rootMargin: '0px 0px -15% 0px' });
  stages.forEach(s => io.observe(s));
}
