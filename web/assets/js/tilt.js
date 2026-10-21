// 3D hover cards: a dependency-free port of the "3D card" pattern (CardContainer / CardBody / CardItem).
//  * mark a container with [data-tilt]; it rotates toward the pointer (perspective 1000px, angle = offset / 25)
//  * children with data-z="40" float toward the viewer while hovered (also data-x, data-y, data-rx, data-ry, data-rz)
//  * one delegated listener, so cards rendered later (project cards) work without re-wiring
//  * mouse only; nothing moves under prefers-reduced-motion
const REDUCED = matchMedia('(prefers-reduced-motion: reduce)').matches;
const MAX = 9;   // degrees
const clamp = v => Math.max(-MAX, Math.min(MAX, v));

function lift(el, on) {
  const d = el.dataset;
  el.style.transform = on
    ? `translateX(${d.x || 0}px) translateY(${d.y || 0}px) translateZ(${d.z || 0}px) rotateX(${d.rx || 0}deg) rotateY(${d.ry || 0}deg) rotateZ(${d.rz || 0}deg)`
    : '';
}

export function tilt(root = document) {
  if (REDUCED || root.__tilt) return;
  root.__tilt = true;
  let cur = null, last = null, raf = 0;

  const enter = c => {
    cur = c;
    c.__t0 = c.style.transform;          // keep whatever transform an entry animation left behind
    c.classList.add('tilt-on');
    c.querySelectorAll('[data-z]').forEach(el => lift(el, true));
  };
  const leave = c => {
    c.classList.remove('tilt-on');
    c.style.transform = c.__t0 || '';
    c.querySelectorAll('[data-z]').forEach(el => lift(el, false));
    if (cur === c) cur = null;
  };
  const frame = () => {
    raf = 0;
    if (!cur || !last) return;
    const r = cur.getBoundingClientRect();
    const x = clamp((last.clientX - r.left - r.width / 2) / 25);
    const y = clamp((last.clientY - r.top - r.height / 2) / 25);
    cur.style.transform = `perspective(1000px) rotateY(${x}deg) rotateX(${-y}deg) translateY(-4px)`;
  };

  root.addEventListener('pointermove', e => {
    if (e.pointerType !== 'mouse') return;
    const c = e.target.closest?.('[data-tilt]');
    if (c !== cur) { if (cur) leave(cur); if (c) enter(c); }
    if (!c) return;
    last = e;
    if (!raf) raf = requestAnimationFrame(frame);
  }, { passive: true });
  root.addEventListener('pointerout', e => { if (cur && !cur.contains(e.relatedTarget)) leave(cur); });
  addEventListener('blur', () => { if (cur) leave(cur); });
}
