// The REVIVE intro before the landing page. Runs before the first paint and decides whether it plays: once per
// browser session (add ?intro to the address to replay it), never under reduced motion. When it plays, the frame rises
// and the mark draws its recovery arrow, the name rises, and the cover lifts like a site hoarding (about 4.2 s; any key or click skips it).
// It needs only Motion (vendored, loaded with defer), so it starts without waiting for the 3D scene. If anything
// fails, CSS lifts the cover after 7 s on its own (landing.css, introSafety).
(() => {
  const root = document.documentElement;
  try {
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    if (sessionStorage.getItem('revive-intro') && !/[?&]intro\b/.test(location.search)) return;
    sessionStorage.setItem('revive-intro', '1');
  } catch { return; }                                  // storage blocked: no intro
  root.classList.add('intro');
  const OUT = [0.16, 1, 0.3, 1], t0 = performance.now();
  const wait = ms => new Promise(res => setTimeout(res, ms));
  const end = cover => { cover?.remove(); root.classList.remove('intro'); root.style.overflow = ''; };

  async function play(M, cover) {
    root.style.overflow = 'hidden';
    let skip;
    const skipped = new Promise(res => { skip = res; });
    addEventListener('pointerdown', skip, { once: true });
    addEventListener('keydown', skip, { once: true });
    await Promise.race([document.fonts?.ready, wait(700)]);     // the name is set in Archivo: never animate the fallback face
    const A = M.animate, q = s => cover.querySelector(s), qa = s => cover.querySelectorAll(s);
    A(q('.intro-mark'), { opacity: [0, 1], scale: [0.86, 1], filter: ['blur(10px)', 'blur(0px)'] }, { duration: 1.1, ease: OUT });
    A(q('.rv-arc'), { strokeDashoffset: [1, 0] }, { duration: 1.8, ease: OUT });
    A(qa('.rv-bar'), { scaleY: [0, 1] }, { type: 'spring', stiffness: 200, damping: 14, delay: M.stagger(0.16, { startDelay: 0.35 }) });
    A(q('.rv-head'), { opacity: [0, 1], scale: [0.3, 1] }, { type: 'spring', stiffness: 420, damping: 16, delay: 1.5 });
    A(qa('.intro-word span'), { y: ['110%', '0%'], opacity: [0, 1], filter: ['blur(10px)', 'blur(0px)'] }, { duration: 1.1, ease: OUT, delay: M.stagger(0.09, { startDelay: 0.7 }) });
    A(q('.intro-word'), { letterSpacing: ['0.3em', '0.06em'] }, { duration: 2.2, ease: OUT, delay: 0.7 });
    A(q('.intro-line i'), { scaleX: [0, 1] }, { duration: 2, ease: OUT, delay: 0.9 });
    A(q('.intro-cap'), { opacity: [0, 1], y: [10, 0] }, { duration: 0.9, ease: OUT, delay: 1.7 });
    await Promise.race([wait(3300), skipped]);
    removeEventListener('pointerdown', skip); removeEventListener('keydown', skip);
    // the hero lines rise out of their masks while the cover lifts
    A(document.querySelectorAll('.h-split>span>span'), { y: ['110%', '0%'], opacity: [0, 1] }, { duration: 1.05, ease: OUT, delay: M.stagger(0.1, { startDelay: 0.12 }) });
    A(document.querySelectorAll('.lede, .cta-row, .hud'), { y: [24, 0], opacity: [0, 1] }, { duration: 0.9, ease: OUT, delay: M.stagger(0.1, { startDelay: 0.38 }) });
    A(q('.intro-core'), { y: -40, opacity: 0, scale: 1.06, filter: 'blur(6px)' }, { duration: 0.55, ease: [0.4, 0, 1, 1] });
    await A(cover, { clipPath: ['inset(0% 0% 0% 0%)', 'inset(0% 0% 100% 0%)'] }, { duration: 0.85, ease: [0.76, 0, 0.24, 1], delay: 0.15 }).finished;
    end(cover);
  }

  (function start() {                                    // Motion arrives with defer; the cover with the body
    const M = window.Motion, cover = document.getElementById('intro');
    if (M && cover) play(M, cover).catch(() => end(cover));
    else if (performance.now() - t0 < 3000) requestAnimationFrame(start);
    else end(cover);
  })();
})();
