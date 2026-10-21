// Talking to the REVIVE server, and staying honest about whether it is there.
//
// The dashboard is a web page served by the Python server (python -m revive serve). The page can
// still be on screen when that server is not running: a browser tab restored from cache, a closed
// terminal window, a laptop that slept. Earlier versions then failed once with "Server not
// reachable" and stayed broken. Here every request classifies its failure, and a monitor keeps
// retrying in the background and resumes the dashboard by itself when the server is back.

export class ApiError extends Error {
  constructor(message, { network = false, status = 0, path = '' } = {}) {
    super(message);
    Object.assign(this, { network, status, path });
  }
}

const listeners = new Set();
export const conn = { state: 'connecting', since: Date.now(), lastOk: 0, attempts: 0 };

// The project the dashboard is working on. The server checks it belongs to the signed-in company
// and runs the request on that project's own schedule and BIM model.
let projectId = null;
export const setProject = id => { projectId = id ? Number(id) : null; };
export const currentProject = () => projectId;

/** Headers every request carries: X-Revive-Request is the CSRF guard (a cross-site form cannot send it). */
export function headers(extra = {}) {
  const h = { 'X-Revive-Request': '1', ...extra };
  if (projectId) h['X-Revive-Project'] = String(projectId);
  return h;
}

/** Session expired or signed out elsewhere: back to the sign-in page, then straight back here. */
function signedOut() {
  if (!signedOut.done) { signedOut.done = true; location.href = '/?next=app#start'; }
}

function setState(state) {
  if (conn.state === state) return;
  conn.state = state;
  conn.since = Date.now();
  listeners.forEach(fn => { try { fn(state); } catch (e) { console.error(e); } });
}
export const onConnChange = fn => listeners.add(fn);

/** fetch() against /api with a timeout. Throws ApiError: .network = true when the server could not be reached. */
export async function api(path, opts = {}) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), opts.timeout ?? 45000);
  let r;
  try {
    r = await fetch('/api' + path, { signal: ctl.signal, ...opts,
      headers: headers({ ...(opts.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }), ...(opts.headers || {}) }) });
  } catch (e) {
    clearTimeout(timer);
    const timedOut = e.name === 'AbortError';
    const err = new ApiError(timedOut ? 'The server took too long to answer' : 'The REVIVE server is not reachable',
      { network: true, path });
    if (!timedOut) noteFailure();
    throw err;
  }
  clearTimeout(timer);
  conn.lastOk = Date.now();
  if (conn.state !== 'online') setState('online');
  if (r.status === 401 && !path.startsWith('/auth/')) { signedOut(); throw new ApiError('Signed out', { status: 401, path }); }
  if (!r.ok) {
    let msg = r.statusText || `HTTP ${r.status}`;
    try { msg = (await r.json()).detail || msg; } catch { /* keep status text */ }
    throw new ApiError(typeof msg === 'string' ? msg : JSON.stringify(msg), { status: r.status, path });
  }
  try { return await r.json(); }
  catch {  // the connection dropped while the answer was arriving
    noteFailure();
    throw new ApiError('The connection to the REVIVE server dropped', { network: true, path });
  }
}
export const post = (path, body, opts = {}) => api(path, { method: 'POST', body: JSON.stringify(body), ...opts });
export const patch = (path, body) => api(path, { method: 'PATCH', body: JSON.stringify(body) });
export const del = path => api(path, { method: 'DELETE' });
/** Multipart upload (IFC, schedule). timeout is long: large IFC models take a while to read. */
export const upload = (path, file, opts = {}) => {
  const fd = new FormData();
  fd.append('file', file);
  return api(path, { method: 'POST', body: fd, timeout: 300000, ...opts });
};
/** Raw fetch with the same headers (used for file downloads). */
export async function rawFetch(path, opts = {}) {
  try { return await fetch('/api' + path, { ...opts, headers: headers(opts.headers || {}) }); }
  catch { const e = new ApiError('The REVIVE server is not reachable', { network: true, path }); noteFailure(); throw e; }
}

/** One cheap liveness check. */
export async function ping(timeout = 4000) {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), timeout);
  try {
    const r = await fetch('/api/ping', { signal: ctl.signal, cache: 'no-store' });
    clearTimeout(t);
    if (!r.ok) return null;
    const d = await r.json();
    return d.app === 'REVIVE' ? d : null;
  } catch { clearTimeout(t); return null; }
}

let loop = null;
/** Called on any network failure: confirm with a ping, then keep retrying until the server answers. */
export function noteFailure() {
  if (loop) return;
  const tick = async () => {
    conn.attempts += 1;
    const ok = await ping(3500);
    if (ok) { loop = null; conn.attempts = 0; conn.lastOk = Date.now(); setState('online'); return; }
    setState('offline');
    loop = setTimeout(tick, Math.min(5000, 1200 + conn.attempts * 400));
  };
  loop = setTimeout(tick, 0);
}

/** Resolve once the server answers. Calls onWait(attempt) while waiting so the UI can show progress. */
export function waitForServer(onWait) {
  return new Promise(resolve => {
    const tryOnce = async n => {
      const ok = await ping(3500);
      if (ok) { conn.lastOk = Date.now(); setState('online'); resolve(ok); return; }
      setState('offline');
      onWait?.(n);
      setTimeout(() => tryOnce(n + 1), Math.min(4000, 800 + n * 300));
    };
    tryOnce(1);
  });
}

/** Background heartbeat: a dropped server is noticed within ~15 s even when nobody clicks anything. */
export function heartbeat(ms = 15000) {
  setInterval(async () => {
    if (document.hidden || loop) return;
    if (Date.now() - conn.lastOk < ms * 0.8) return;
    const ok = await ping(5000);
    if (ok) { conn.lastOk = Date.now(); if (conn.state !== 'online') setState('online'); }
    else noteFailure();
  }, ms);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) ping(4000).then(ok => ok ? setState('online') : noteFailure()); });
}
