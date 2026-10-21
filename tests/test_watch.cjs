const test = require('node:test');
const assert = require('node:assert/strict');
const Watch = require('../frontend/assets/watch.js');
function clock() {
  let id = 0; const timers = new Map();
  return { timers, setTimeout(fn, ms) { timers.set(++id, { fn, ms }); return id; },
    clearTimeout(id) { timers.delete(id); } };
}
const flush = () => new Promise(resolve => setImmediate(resolve));
test('stop cancels the active request and prevents rescheduling after it resolves', async () => {
  const c = clock(); let finish, signal, calls = 0;
  const monitor = new Watch(s => { signal = s; calls++; return new Promise(r => finish = r); }, () => {}, c);
  monitor.start(); monitor.start();
  assert.equal(calls, 1);
  monitor.stop();
  assert.ok(signal.aborted);
  finish(); await flush();
  assert.equal(c.timers.size, 0);
  assert.equal(monitor.running, false);
});
test('only schedules the next frame after the previous observation completes', async () => {
  const c = clock(); let finish;
  const monitor = new Watch(() => new Promise(r => finish = r), () => {}, c);
  monitor.start();
  assert.deepEqual([...c.timers.values()].map(t => t.ms), [1800000]);
  finish(); await flush();
  assert.deepEqual([...c.timers.values()].map(t => t.ms), [1800000, 31000]);
  monitor.stop();
});
test('quota errors stop paid retries', async () => {
  const c = clock();
  const monitor = new Watch(async () => { throw Object.assign(new Error('quota'), { quota: true }); }, () => {}, c);
  monitor.start(); await flush();
  assert.equal(monitor.running, false);
  assert.equal(c.timers.size, 0);
});
test('stopping an old session cannot schedule another frame in a new session', async () => {
  const c = clock(); const pending = [];
  const monitor = new Watch(() => new Promise(r => pending.push(r)), () => {}, c);
  monitor.start(); monitor.stop(); monitor.start();
  pending[0](); await flush();
  assert.equal(c.timers.size, 1);
  pending[1](); await flush();
  assert.equal(c.timers.size, 2);
  monitor.stop();
});
