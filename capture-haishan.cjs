'use strict';
// Passive CDP listener for Haishan pages in the user-approved dedicated Chrome.
// It performs no clicks and writes only redacted request/response structure.
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const crypto = require('node:crypto');

const SECRET = /cookie|token|signature|authorization|password|passwd|secret|credential|session|captcha|verify_code|phone|email|user_id|account_id|device_id|fingerprint|msToken|a_bogus|x_bogus|policy|signed|upload_id|storage_key|(^|_)uri($|_)/i;
const SAFE_VALUES = new Set(['type', 'sub_type', 'scene', 'biz', 'action', 'source', 'status', 'code', 'version', 'app_id', 'aid', 'model', 'model_name', 'resolution', 'duration', 'ratio', 'count', 'offset', 'limit', 'page', 'page_size', 'resource_type', 'media_type', 'source_type', 'entry_type', 'format', 'success', 'method', 'link_type']);
const LOGIN = /passport|oauth|login|logout|captcha|send_sms|verify_sms|auth\/|\/auth$|\/account(?:\/|$)/i;
const TELEMETRY = /\/monitor|\/report|\/track|\/log(?:\/|$)|\/collect(?:\/|$)/i;

function digest(value) { return crypto.createHash('sha256').update(String(value)).digest('hex').slice(0, 12); }
function routePath(value) {
  return value.split('/').map(p => /^[0-9]{6,}$/.test(p) || /^[a-f0-9-]{24,}$/i.test(p) || p.length > 70 ? '[opaque]' : p).join('/');
}
function redact(value, key = '', depth = 0) {
  if (SECRET.test(key)) return '[redacted]';
  if (depth > 9) return '[depth-limit]';
  if (Array.isArray(value)) return value.slice(0, 8).map(v => redact(v, key, depth + 1));
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).slice(0, 120).map(([k, v]) => [k, redact(v, k, depth + 1)]));
  if (value === null || typeof value === 'boolean') return value;
  if (typeof value === 'number') return SAFE_VALUES.has(key) ? value : '[number]';
  if (typeof value === 'string') {
    if (/^https?:\/\//i.test(value)) return '[url]';
    if (SAFE_VALUES.has(key) && value.length < 100 && !/[\r\n]/.test(value) && !/[A-Za-z0-9+/_=-]{40,}/.test(value)) return value;
    if (/(^|_)id$|_ids$|^id$|^ids$/i.test(key)) return '[id:' + digest(value) + ']';
    return value === '' ? '' : '[string]';
  }
  return '[unknown]';
}
function safeBody(text, contentType = '') {
  if (!text) return null;
  if (text.length > 1024 * 1024) return { omitted: 'body over 1MiB' };
  try { return redact(JSON.parse(text)); } catch {}
  if (contentType.includes('application/x-www-form-urlencoded')) return redact(Object.fromEntries(new URLSearchParams(text)));
  return { omitted: 'non-json or binary body', length: text.length };
}
function safeUrl(value) {
  const u = new URL(value);
  const query = {};
  for (const [k, v] of u.searchParams) query[k] = redact(v, k);
  return { origin: u.origin, path: routePath(u.pathname), query };
}
function safeHeaders(headers) {
  const out = {};
  for (const [k, v] of Object.entries(headers || {})) {
    const lower = k.toLowerCase();
    if (['content-type', 'accept', 'content-disposition', 'content-length'].includes(lower)) out[lower] = SECRET.test(lower) ? '[redacted]' : String(v).split(';')[0].slice(0, 160);
  }
  return out;
}
function haishanPage(url) {
  try { const host = new URL(url).hostname; return host === 'mikooo.cn' || host.endsWith('.mikooo.cn'); } catch { return false; }
}
function eligible(url, type, method) {
  try {
    const u = new URL(url);
    return u.protocol === 'https:' && !LOGIN.test(u.pathname) && !TELEMETRY.test(u.pathname) && (['XHR', 'Fetch'].includes(type) || ['POST', 'PUT', 'PATCH', 'DELETE'].includes(method));
  } catch { return false; }
}

async function main() {
  const port = Number(process.env.HAISHAN_DEBUG_PORT || 9227);
  const statusPort = Number(process.env.HAISHAN_CAPTURE_PORT || 9231);
  const directory = path.join(__dirname, '.data', 'network-capture');
  fs.mkdirSync(directory, { recursive: true });
  const output = path.join(directory, 'haishan-requests.jsonl');
  const status = { running: true, connected: false, attachedPages: 0, capturedThisRun: 0, downloads: 0, lastCapture: null, lastDownload: null, error: null, debugPort: port, output };
  const sessions = new Map(), requests = new Map(), pending = new Map();
  let seq = 0, ws = null;

  function write(record) {
    fs.appendFileSync(output, JSON.stringify(record) + '\n', { encoding: 'utf8', mode: 0o600 });
    status.capturedThisRun++;
    status.lastCapture = { time: record.time, method: record.method, origin: record.url?.origin, path: record.url?.path, status: record.response?.status };
    console.log(`[haishan] ${record.method || record.event} ${record.url?.origin || ''}${record.url?.path || ''} ${record.response?.status || ''}`.trim());
  }
  function send(method, params = {}, sessionId) {
    return new Promise((resolve, reject) => {
      const id = ++seq;
      const timer = setTimeout(() => { pending.delete(id); reject(new Error('CDP command timed out')); }, 15000);
      pending.set(id, { resolve, reject, timer });
      ws.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
    });
  }
  async function attach(info) {
    if (info.type !== 'page' || [...sessions.values()].some(s => s.targetId === info.targetId)) return;
    try {
      const { sessionId } = await send('Target.attachToTarget', { targetId: info.targetId, flatten: true });
      sessions.set(sessionId, { targetId: info.targetId, url: info.url || '' });
      status.attachedPages = sessions.size;
      await send('Network.enable', { maxTotalBufferSize: 16 * 1024 * 1024, maxResourceBufferSize: 8 * 1024 * 1024 }, sessionId);
      await send('Page.enable', {}, sessionId).catch(() => {});
    } catch {}
  }
  async function finish(sid, requestId, failed) {
    const key = sid + ':' + requestId;
    const item = requests.get(key);
    if (!item) return;
    requests.delete(key);
    if (failed) item.record.failed = true;
    const mime = String(item.response?.mimeType || '').toLowerCase();
    if (!failed && (mime.includes('json') || mime.includes('text/plain')) && item.size <= 512 * 1024) {
      try {
        const body = await send('Network.getResponseBody', { requestId }, sid);
        const text = body.base64Encoded ? Buffer.from(body.body, 'base64').toString('utf8') : body.body;
        try { item.record.responseBody = redact(JSON.parse(text)); } catch { item.record.responseBody = { omitted: 'non-json response', length: text.length }; }
      } catch { item.record.responseBody = { omitted: 'response body unavailable' }; }
    }
    write(item.record);
  }

  async function connect() {
    try {
      const version = await fetch(`http://127.0.0.1:${port}/json/version`, { signal: AbortSignal.timeout(3000) }).then(r => r.json());
      const url = new URL(version.webSocketDebuggerUrl);
      if (url.hostname !== '127.0.0.1' || url.protocol !== 'ws:') throw new Error('Unexpected debugging address');
      ws = new WebSocket(url);
      await new Promise((resolve, reject) => { ws.addEventListener('open', resolve, { once: true }); ws.addEventListener('error', reject, { once: true }); });
      status.connected = true;
      status.error = null;
      ws.addEventListener('message', event => {
        (async () => {
          const m = JSON.parse(event.data);
          if (m.id) {
            const p = pending.get(m.id);
            if (p) { clearTimeout(p.timer); pending.delete(m.id); m.error ? p.reject(new Error('CDP command rejected')) : p.resolve(m.result); }
            return;
          }
          const p = m.params || {}, sid = m.sessionId;
          if (m.method === 'Target.targetCreated') { await attach(p.targetInfo); return; }
          if (m.method === 'Target.targetInfoChanged') {
            for (const s of sessions.values()) if (s.targetId === p.targetInfo.targetId) s.url = p.targetInfo.url || s.url;
            return;
          }
          if (m.method === 'Target.detachedFromTarget') { sessions.delete(p.sessionId); status.attachedPages = sessions.size; return; }
          const page = sessions.get(sid);
          if (!page || !haishanPage(page.url)) return;
          const key = sid + ':' + p.requestId;
          if (m.method === 'Network.requestWillBeSent' && eligible(p.request.url, p.type, p.request.method)) {
            const r = p.request;
            if (new URL(r.url).hostname === 'www.mikooo.cn' && ['/desktop/story/list-element/', '/desktop/story/list-element-category/'].includes(new URL(r.url).pathname)) {
              try { const b = JSON.parse(r.postData || '{}'); const allowed = ['movie_id','type','page','page_size','name','is_assets','link_type','category_id','group_id']; const clean = Object.fromEntries(Object.entries(b).filter(([k]) => allowed.includes(k))); const file = path.join(directory, 'haishan-list-parameters.json'); let prior = {}; try { prior = JSON.parse(fs.readFileSync(file,'utf8')); } catch {} prior[new URL(r.url).pathname] = clean; fs.writeFileSync(file, JSON.stringify(prior,null,2)); } catch {}
            }
            requests.set(key, {
              time: Date.now(),
              record: { time: new Date().toISOString(), method: r.method, type: p.type, url: safeUrl(r.url), headers: safeHeaders(r.headers), requestBody: safeBody(r.postData, Object.entries(r.headers || {}).find(([k]) => k.toLowerCase() === 'content-type')?.[1] || '') },
              size: 0
            });
          } else if (m.method === 'Network.responseReceived' && requests.has(key)) {
            const item = requests.get(key);
            item.response = p.response;
            item.record.response = { status: p.response.status, mimeType: p.response.mimeType, headers: safeHeaders(p.response.headers) };
          } else if (m.method === 'Network.loadingFinished' && requests.has(key)) {
            requests.get(key).size = p.encodedDataLength;
            await finish(sid, p.requestId, false);
          } else if (m.method === 'Network.loadingFailed' && requests.has(key)) {
            await finish(sid, p.requestId, true);
          } else if (m.method === 'Page.downloadWillBegin') {
            status.downloads++;
            const u = safeUrl(p.url);
            status.lastDownload = { time: new Date().toISOString(), origin: u.origin, path: u.path, suggestedFilename: '[redacted-filename]' };
            write({ time: status.lastDownload.time, event: 'download-will-begin', url: u, suggestedFilename: '[redacted-filename]', guid: '[redacted]' });
          }
        })().catch(() => { status.error = 'A capture event could not be processed; no raw data was logged.'; });
      });
      ws.addEventListener('close', () => { status.connected = false; sessions.clear(); status.attachedPages = 0; requests.clear(); setTimeout(connect, 3000); });
      await send('Target.setDiscoverTargets', { discover: true });
      const { targetInfos } = await send('Target.getTargets');
      for (const info of targetInfos) await attach(info);
      console.log('Haishan passive capture ready. Sensitive fields are redacted before disk writes.');
    } catch {
      status.connected = false;
      status.error = 'Waiting for the dedicated Chrome debugging port';
      setTimeout(connect, 3000);
    }
  }

  setInterval(() => { for (const [key, item] of requests) if (Date.now() - item.time > 300000) requests.delete(key); }, 60000).unref();
  const server = http.createServer((req, res) => {
    if (req.url === '/status') { res.writeHead(200, { 'content-type': 'application/json' }); res.end(JSON.stringify(status)); return; }
    res.writeHead(404); res.end();
  });
  server.listen(statusPort, '127.0.0.1', () => console.log(`Local Haishan capture status: http://127.0.0.1:${statusPort}/status`));
  await connect();
  function stop() { status.running = false; for (const p of pending.values()) clearTimeout(p.timer); ws?.close(); server.close(); process.exit(0); }
  process.on('SIGINT', stop);
  process.on('SIGTERM', stop);
}

if (require.main === module) main().catch(() => { console.error('Capture startup failed. Check local ports.'); process.exitCode = 1; });
module.exports = { redact, safeBody, safeUrl, eligible, haishanPage };

