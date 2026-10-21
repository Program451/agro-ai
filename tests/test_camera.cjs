const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../frontend/assets/camera.js'), 'utf8');
function camera(mediaDevices) {
  return vm.runInNewContext(source + '\ncameraAccess;', { navigator: { mediaDevices } });
}
test('OBS already visible: listing does not open the default webcam used by OBS', async () => {
  const access = camera({
    enumerateDevices: async () => [{ kind: 'videoinput', label: 'OBS Virtual Camera', deviceId: 'obs' }],
    getUserMedia: async () => { throw new Error('The physical webcam is busy in OBS'); }
  });
  assert.equal((await access.devices(true))[0].deviceId, 'obs');
});
test('Permission probe stays open until labels are read, then releases every track', async () => {
  let opened = false, stopped = false, reads = 0;
  const access = camera({
    enumerateDevices: async () => {
      reads++;
      if (reads === 2) assert.equal(opened && !stopped, true);
      return [{ kind: 'videoinput', label: opened ? 'OBS Virtual Camera' : '', deviceId: 'obs' }];
    },
    getUserMedia: async (options) => {
      assert.equal(options.audio, false);
      opened = true;
      return { getTracks: () => [{ stop: () => { stopped = true; } }] };
    }
  });
  assert.equal((await access.devices(true))[0].label, 'OBS Virtual Camera');
  assert.equal(stopped, true);
});
test('Failed enumeration releases the temporary stream', async () => {
  let reads = 0, stopped = false;
  const access = camera({
    enumerateDevices: async () => { if (++reads > 1) throw new Error('Device removed'); return []; },
    getUserMedia: async () => ({ getTracks: () => [{ stop: () => { stopped = true; } }] })
  });
  await assert.rejects(access.devices(true), /Device removed/);
  assert.equal(stopped, true);
});
test('Passive listing never asks for access; system denial gives actionable Russian help', async () => {
  let requests = 0;
  const denied = Object.assign(new Error('Permission denied by system'), { name: 'NotAllowedError' });
  const access = camera({
    enumerateDevices: async () => [],
    getUserMedia: async () => { requests++; throw denied; }
  });
  await access.devices(false);
  assert.equal(requests, 0);
  await assert.rejects(access.devices(true), /Permission denied/);
  assert.match(access.errorMessage(denied), /отдельный браузер/);
});
test('HTTP without media APIs explains the secure context requirement', async () => {
  await assert.rejects(camera(undefined).devices(true), /HTTPS/);
});
