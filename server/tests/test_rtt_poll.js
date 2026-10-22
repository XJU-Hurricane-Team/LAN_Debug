// Offline execution of the actual page poller. No HTTP, service, SDK or device access.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync(path.join(__dirname, '../templates/index.html'), 'utf8');
const code = html.slice(html.indexOf('    function pollRTTOnce() {'), html.indexOf('    function appendRTTLines(lines) {'));
const requests = [], rendered = [];
const state = {
  displayedSN: 'offline-a', rttLineIndex: 0, rttCurrentlyActive: false, rttPollPending: false,
  fetch(url) { return new Promise((resolve, reject) => requests.push({url, resolve, reject})); },
  appendRTTLines(lines) { rendered.push(...lines); },
  document: {querySelector() { return null; }}, setStatusUI() {}, updateToggleBtn() {}, console: {error() {}}
};
vm.createContext(state); vm.runInContext(code, state);
const flush = () => new Promise(resolve => setImmediate(resolve));
(async () => {
  state.pollRTTOnce(); state.pollRTTOnce();
  assert.equal(requests.length, 1, 'only one request may own the current cursor');
  requests[0].resolve({json: async () => ({lines: ['C07 seq=4490 ramp=90'], index: 1, active: true})});
  await flush(); assert.deepEqual(rendered, ['C07 seq=4490 ramp=90']);
  state.pollRTTOnce(); assert.match(requests[1].url, /since=1$/);
  state.displayedSN = 'offline-b';
  requests[1].resolve({json: async () => ({lines: ['wrong device'], index: 99, active: true})});
  await flush(); assert.equal(rendered.length, 1); assert.equal(state.rttLineIndex, 1);
  state.rttLineIndex = 0; state.pollRTTOnce();
  requests[2].reject(new Error('offline failure')); await flush();
  assert.equal(state.rttPollPending, false);
  state.pollRTTOnce(); assert.equal(requests.length, 4);
  requests[3].resolve({json: async () => ({lines: ['next'], index: 1, active: false})});
  await flush(); assert.deepEqual(rendered, ['C07 seq=4490 ramp=90', 'next']);
  console.log('PASS overlap, cursor advance, device switch, rejected request and retry; offline only');
})().catch(error => { console.error(error); process.exitCode = 1; });
