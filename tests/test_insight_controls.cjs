const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { webcrypto } = require('node:crypto');
const root = path.join(__dirname, '..');

function screen(mode = 'photo', input = true) {
  const events = {}, requests = [], watches = [];
  const nodes = new Map([...fs.readFileSync(path.join(root, 'frontend/index.php'), 'utf8')
    .matchAll(/id="([^"]+)"/g)].map(([, id]) => [id, {
      hidden: false, disabled: false, textContent: '', handlers: {},
      addEventListener(event, fn) { this.handlers[event] = fn; },
      scrollIntoView() {}, replaceChildren() {}, append() {},
    }]));
  class Watch {
    constructor(take, status) { this.running = false; this.status = status; this.starts = 0; watches.push(this); }
    start() { this.running = true; this.starts++; }
    stop(message) { this.running = false; this.status(message); }
  }
  const document = {
    hidden: false,
    addEventListener: (name, fn) => { events[name] = fn; },
    createElement: () => ({ getContext: () => ({ drawImage() {} }), toDataURL: () => 'data:image/jpeg;base64,cGl4ZWxz' }),
  };
  const context = vm.createContext({
    $: id => nodes.get(id) || null, mode, file: input ? {} : null,
    live: mode === 'camera' && input, busy: false, ready: true, adviceAvailable: true,
    originalUrl: 'blob:local-photo', crypto: webcrypto, AbortController, DOMException,
    document, window: { addEventListener() {} }, AgroWatch: Watch,
    Image: class { naturalWidth = 40; naturalHeight = 30; async decode() {} },
    api: async (url, options) => {
      if (url === '/insights/history') return { observations: [] };
      requests.push({ url, payload: JSON.parse(options.body), signal: options.signal });
      // No provider request in this test. The UI must recover and permit retry.
      throw new Error('Test provider unavailable');
    },
  });
  vm.runInContext(fs.readFileSync(path.join(root, 'frontend/assets/insights.js'), 'utf8'), context);
  return { context, nodes, requests, watch: watches[0], events, document };
}

test('file uses the remaining button for one request and can retry a failure', async () => {
  const ui = screen();
  assert.equal(ui.nodes.has('ai-once'), false);
  assert.equal(ui.nodes.has('ai-start'), false);
  await ui.nodes.get('advice').handlers.click();
  assert.equal(ui.requests.length, 1);
  assert.equal(ui.requests[0].payload.source, 'photo');
  assert.match(ui.requests[0].payload.image, /^data:image\/jpeg/);
  assert.equal(ui.watch.starts, 0);
  assert.equal(ui.nodes.get('advice').disabled, false);
  assert.equal(ui.nodes.get('ai-stop').hidden, true);
});

test('camera watch requires a click, prevents duplicate starts and remains stoppable', async () => {
  const ui = screen('camera');
  assert.equal(ui.watch.starts, 0);
  await ui.nodes.get('advice').handlers.click();
  await ui.nodes.get('advice').handlers.click();
  assert.equal(ui.watch.starts, 1);
  assert.equal(ui.nodes.get('ai-stop').hidden, false);
  ui.nodes.get('ai-stop').handlers.click();
  assert.equal(ui.watch.running, false);
  assert.equal(ui.nodes.get('advice').disabled, false);
});

test('missing media cannot start cloud work', async () => {
  const ui = screen('camera', false);
  await ui.nodes.get('advice').handlers.click();
  assert.equal(ui.watch.starts, 0);
  assert.equal(ui.requests.length, 0);
});

test('hiding the page stops continuous observations', async () => {
  const ui = screen('camera');
  await ui.nodes.get('advice').handlers.click();
  ui.document.hidden = true;
  ui.events.visibilitychange();
  assert.equal(ui.watch.running, false);
  assert.match(ui.nodes.get('ai-status').textContent, /Gemini \+ датчики/);
});
