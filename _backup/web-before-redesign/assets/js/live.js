// Live site link, dashboard side.
//
// One Server-Sent Events connection (/api/live/stream) carries every monitored project's events:
//   update    a phone sent a site update (already re-scored by the server)
//   presence  a phone has the update page open
//   project   a new monitored project was started (on this or another dashboard)
//   ping      every 10 s, so a silent but dead connection is detected
// Beside the stream, the followed project is polled for missed updates (/updates?after=<id>).
// Updates carry ids, so whichever path delivers one first wins and the other is ignored.
// Result: a phone update reaches the dashboard even across Wi-Fi drops, sleep or a server restart.
import { api } from './conn.js';

export class LiveChannel {
  constructor({ onUpdate, onPresence, onProject, onStatus }) {
    Object.assign(this, { onUpdate, onPresence, onProject, onStatus });
    this.es = null;
    this.pid = null;
    this.lastId = 0;
    this.seen = new Set();
    this.queue = Promise.resolve();
    this.lastEvent = 0;
    this.status = 'off';
  }

  start() {
    this._connect();
    setInterval(() => this._watchdog(), 5000);
    setInterval(() => this.catchUp(), 6000);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) { this._watchdog(true); this.catchUp(); } });
  }

  /** Follow one project: its updates are applied to the dashboard; lastId = newest update already shown. */
  follow(pid, lastId = 0) {
    this.pid = pid ? Number(pid) : null;
    this.lastId = lastId || 0;
  }

  markSeen(id) {
    this.seen.add(id);
    if (id > this.lastId) this.lastId = id;
  }

  _set(s) { if (this.status !== s) { this.status = s; this.onStatus?.(s); } }

  _connect() {
    if (this.es) { try { this.es.close(); } catch { /* already closed */ } }
    this._set('connecting');
    const es = new EventSource('/api/live/stream');
    this.es = es;
    const alive = () => { this.lastEvent = Date.now(); };
    es.onopen = () => { alive(); this._set('live'); this.catchUp(); };
    es.onerror = () => { if (this.es === es) this._set('reconnecting'); };
    es.addEventListener('hello', alive);
    es.addEventListener('ping', alive);
    es.addEventListener('update', e => { alive(); this._enqueue(JSON.parse(e.data)); });
    es.addEventListener('presence', e => { alive(); this.onPresence?.(JSON.parse(e.data)); });
    es.addEventListener('project', e => { alive(); this.onProject?.(JSON.parse(e.data)); });
  }

  _watchdog(force = false) {
    // EventSource reconnects by itself after an error; a stream that stays silent for
    // more than 25 s (pings arrive every 10 s) is dead without an error, so reopen it.
    const silent = Date.now() - this.lastEvent > 25000;
    if (!this.es || this.es.readyState === EventSource.CLOSED || (silent && (force || this.status === 'live'))) this._connect();
  }

  _enqueue(msg) {
    const id = msg?.update?.id;
    if (id == null || this.seen.has(id)) return;
    this.seen.add(id);
    // apply one at a time, in order: each one re-plans the recovery
    this.queue = this.queue.then(async () => {
      try { await this.onUpdate?.(msg); } catch (e) { console.error('live update failed', e); }
      if (msg.project_id === this.pid && id > this.lastId) this.lastId = id;
    });
  }

  /** Fetch updates the stream may have missed for the followed project. */
  async catchUp() {
    if (!this.pid || this._busy) return;
    this._busy = true;
    try {
      const ups = await api(`/live/${this.pid}/updates?after=${this.lastId}`, { timeout: 15000 });
      ups.forEach(m => this._enqueue(m));
    } catch { /* offline: the connection monitor shows it; try again next round */ }
    finally { this._busy = false; }
  }
}
