// Offline execution of the actual page poller. No HTTP, service, SDK or device access.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync(path.join(__dirname, '../templates/index.html'), 'utf8');
const code = html.slice(html.indexOf('    function pollRTTOnce() {'), html.indexOf('    function appendRTTLines(lines) {'));
const requests = [], rendered = [], timers = new Map();
let timerId = 0;
const state = {
  displayedSN: 'offline-a', rttLineIndex: 0, rttCurrentlyActive: false, rttPollPending: false,
  fetch(url, options) { return new Promise((resolve, reject) => {
    requests.push({url, resolve, reject, signal: options?.signal});
    options?.signal.addEventListener('abort', () => reject(new Error('aborted')));
  }); },
  AbortController,
  setTimeout(callback) { timers.set(++timerId, callback); return timerId; },
  clearTimeout(id) { timers.delete(id); },
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
  assert.ok(!state.rttPollPending);
  state.pollRTTOnce(); assert.equal(requests.length, 4);
  requests[3].resolve({json: async () => ({lines: ['next'], index: 1, active: false})});
  await flush(); assert.deepEqual(rendered, ['C07 seq=4490 ramp=90', 'next']);
  state.pollRTTOnce();
  assert.equal(timers.size, 1, 'a hung request has a deadline');
  [...timers.values()][0](); await flush();
  assert.equal(requests[4].signal.aborted, true);
  state.pollRTTOnce(); assert.equal(requests.length, 6);
  state.displayedSN = 'offline-c'; state.rttLineIndex = 0; state.pollRTTOnce();
  assert.equal(requests[5].signal.aborted, true, 'switch cancels the old pending request');
  assert.equal(requests.length, 7); await flush();
  state.pollRTTOnce(); assert.equal(requests.length, 7, 'old finally cannot unlock the new request');
  requests[6].resolve({json: async () => ({lines: ['switched'], index: 1, active: false})});
  await flush(); assert.equal(rendered.at(-1), 'switched'); assert.equal(timers.size, 0);
  console.log('PASS overlap, cursor advance, switch, rejection, timeout and retry; offline only');
})().catch(error => { console.error(error); process.exitCode = 1; });
