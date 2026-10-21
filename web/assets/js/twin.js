// Three.js viewer for the IFC geometry served by /api/bim/geometry.
// IFC is Z-up; the model group is rotated so Three.js (Y-up) shows it upright.
// Colour changes (a new forecast, a live site update) blend over ~0.6 s instead of snapping,
// elements highlight under the pointer, and the camera flies in when a model loads.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

export class Twin {
  constructor(canvas, { interactive = true, autoRotate = false } = {}) {
    this.canvas = canvas;
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.setClearColor(0x000000, 0);
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(32, 1, 0.1, 5000);
    this.root = new THREE.Group();
    this.root.rotation.x = -Math.PI / 2;
    this.scene.add(this.root);
    this.scene.add(new THREE.HemisphereLight(0xe8f4ff, 0x12161c, 1.25));
    const sun = new THREE.DirectionalLight(0xffffff, 1.5);
    sun.position.set(40, 80, 30);
    this.scene.add(sun);
    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.enableDamping = true;
    this.controls.autoRotate = autoRotate;
    this.controls.autoRotateSpeed = 0.45;
    this.controls.enabled = interactive;
    this.meshes = new Map();
    this.tick = null;
    this.hovered = null;
    this._style = null;
    this._fading = false;
    this._fly = null;
    this.reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
    this.visible = true;
    this._last = performance.now();
    if (interactive) { this._bindPick(); this._bindHover(); }
    this.controls.addEventListener('start', () => { this._fly = null; });
    new ResizeObserver(() => this.resize()).observe(canvas);
    new IntersectionObserver(([e]) => { this.visible = e.isIntersecting; }).observe(canvas);
    this.resize();
    this._loop();
  }

  resize() {
    const w = this.canvas.clientWidth || 1, h = this.canvas.clientHeight || 1;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  clear() {
    this.meshes.forEach(m => { m.geometry.dispose(); m.material.dispose(); m.children.forEach(c => { c.geometry.dispose(); c.material.dispose(); }); this.root.remove(m); });
    this.meshes.clear();
    if (this.grid) { this.scene.remove(this.grid); this.grid = null; }
  }

  load(geom, { framing = 'default' } = {}) {
    this.clear();
    for (const m of geom.meshes) {
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.Float32BufferAttribute(m.verts, 3));
      g.setIndex(m.faces);
      g.computeVertexNormals();
      const mat = new THREE.MeshStandardMaterial({ color: 0xb4bcc6, roughness: 0.82, metalness: 0.04, flatShading: true, transparent: true });
      const mesh = new THREE.Mesh(g, mat);
      mesh.userData = { guid: m.guid, name: m.name, ifc_class: m.ifc_class, storey: m.storey, activity: m.activity, material: m.material };
      const edges = new THREE.LineSegments(new THREE.EdgesGeometry(g, 25), new THREE.LineBasicMaterial({ color: 0xe6eef1, transparent: true, opacity: 0.22 }));
      mesh.add(edges);
      this.root.add(mesh);
      this.meshes.set(m.guid, mesh);
    }
    const [x0, y0, z0] = geom.bounds.min, [x1, y1, z1] = geom.bounds.max;
    const center = new THREE.Vector3((x0 + x1) / 2, (z0 + z1) / 2, -(y0 + y1) / 2);
    const radius = Math.hypot(x1 - x0, y1 - y0, z1 - z0) / 2 || 10;
    const span = Math.max(x1 - x0, y1 - y0) * 2.2;
    this.grid = new THREE.GridHelper(span, Math.round(span / 3), 0x5a6573, 0x262d37);
    this.grid.material.transparent = true;
    this.grid.material.opacity = 0.35;
    this.grid.position.set(center.x, z0 - 0.02, center.z);
    this.scene.add(this.grid);
    this.controls.target.copy(center);
    const dir = framing === 'hero' ? new THREE.Vector3(1.0, 0.55, 1.1) : new THREE.Vector3(1.0, 0.62, 1.3);
    this.camera.position.copy(center).add(dir.normalize().multiplyScalar(radius * (framing === 'hero' ? 3.6 : 3.4)));
    if (framing === 'hero') { const side = new THREE.Vector3().subVectors(this.camera.position, center).cross(new THREE.Vector3(0, 1, 0)).normalize(); this.controls.target.addScaledVector(side, radius * 0.75); }
    this.camera.near = radius / 50; this.camera.far = radius * 50;
    this.camera.updateProjectionMatrix();
    if (!this.reduced) {
      const to = this.camera.position.clone(), from = this.controls.target.clone().add(to.clone().sub(this.controls.target).multiplyScalar(2.4));
      from.y += radius * 1.2;
      this.camera.position.copy(from);
      this._fly = { from, to, t0: performance.now(), dur: 1700 };
    }
    this.controls.update();
  }

  // style(u) -> {visible, color, opacity, glow, edge, lift}
  // opts.instant: apply at once (playback, scrubbing, the hero assembly); otherwise blend.
  paint(style, { instant = false } = {}) {
    this._style = style;
    const now = instant || this.reduced;
    for (const mesh of this.meshes.values()) {
      const s = style(mesh.userData) || {};
      mesh.visible = s.visible !== false;
      if (!mesh.visible) continue;
      const mat = mesh.material, op = s.opacity ?? 1, guid = mesh.userData.guid;
      const hi = guid === this.selected ? 0.35 : guid === this.hovered ? 0.22 : 0;
      const t = mesh.userData._t || (mesh.userData._t = { color: new THREE.Color(), emissive: new THREE.Color() });
      t.color.set(s.color || '#b4bcc6');
      t.emissive.set(hi ? '#ffffff' : (s.color || '#000000'));
      t.opacity = op;
      t.ei = hi || (s.glow || 0);
      t.edge = s.edge ?? (op < 0.3 ? 0.12 : 0.22);
      mat.depthWrite = op > 0.95;
      mesh.position.z = s.lift || 0;
      if (now) {
        mat.color.copy(t.color); mat.emissive.copy(t.emissive); mat.opacity = t.opacity; mat.emissiveIntensity = t.ei;
        mesh.children[0].material.opacity = t.edge;
      }
    }
    this._fading = !now;
  }

  repaint() { if (this._style) this.paint(this._style, { instant: true }); }

  _blend(dt) {
    const k = 1 - Math.exp(-dt * 7);
    let moving = false;
    for (const mesh of this.meshes.values()) {
      const t = mesh.userData._t;
      if (!t || !mesh.visible) continue;
      const mat = mesh.material, e = mesh.children[0].material;
      mat.color.lerp(t.color, k); mat.emissive.lerp(t.emissive, k);
      mat.opacity += (t.opacity - mat.opacity) * k;
      mat.emissiveIntensity += (t.ei - mat.emissiveIntensity) * k;
      e.opacity += (t.edge - e.opacity) * k;
      if (Math.abs(mat.opacity - t.opacity) > 0.004 || Math.abs(mat.color.r - t.color.r) + Math.abs(mat.color.g - t.color.g) + Math.abs(mat.color.b - t.color.b) > 0.006) moving = true;
    }
    this._fading = moving;
  }

  onPick(cb) { this._pick = cb; }
  onHover(cb) { this._hover = cb; }

  _bindHover() {
    const ray = new THREE.Raycaster(), p = new THREE.Vector2();
    let pending = null;
    const run = () => {
      const e = pending; pending = null;
      if (!e) return;
      const r = this.canvas.getBoundingClientRect();
      p.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
      ray.setFromCamera(p, this.camera);
      const hit = ray.intersectObjects([...this.meshes.values()].filter(m => m.visible && m.material.opacity > 0.3), false)[0];
      const guid = hit ? hit.object.userData.guid : null;
      if (guid !== this.hovered) { this.hovered = guid; this.canvas.style.cursor = guid ? 'pointer' : ''; this.repaint(); }
      this._hover?.(hit ? hit.object.userData : null, e.clientX, e.clientY);
    };
    this.canvas.addEventListener('pointermove', e => {
      if (e.buttons) { if (this.hovered) { this.hovered = null; this.repaint(); this._hover?.(null); } return; }
      if (!pending) requestAnimationFrame(run);
      pending = { clientX: e.clientX, clientY: e.clientY };
    });
    this.canvas.addEventListener('pointerleave', () => { pending = null; if (this.hovered) { this.hovered = null; this.repaint(); } this._hover?.(null); });
  }

  _bindPick() {
    const ray = new THREE.Raycaster(), p = new THREE.Vector2();
    let down = null;
    this.canvas.addEventListener('pointerdown', e => { down = [e.clientX, e.clientY]; });
    this.canvas.addEventListener('pointerup', e => {
      if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 5) return;
      const r = this.canvas.getBoundingClientRect();
      p.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
      ray.setFromCamera(p, this.camera);
      const hit = ray.intersectObjects([...this.meshes.values()].filter(m => m.visible && m.material.opacity > 0.3), false)[0];
      this.selected = hit ? hit.object.userData.guid : null;
      if (this._pick) this._pick(hit ? hit.object.userData : null);
    });
  }

  _loop() {
    requestAnimationFrame(() => this._loop());
    const now = performance.now(), dt = Math.min(0.1, (now - this._last) / 1000);
    this._last = now;
    if (!this.visible) return;
    if (this.tick) this.tick(dt);
    if (this._fading) this._blend(dt);
    if (this._fly) {
      const f = this._fly, p = Math.min(1, (now - f.t0) / f.dur), e = 1 - Math.pow(1 - p, 3);
      this.camera.position.lerpVectors(f.from, f.to, e);
      if (p >= 1) this._fly = null;
    }
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  }
}
