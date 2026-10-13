// Exercise exported client data and invalid-device cases without a probe/server.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync('templates/index.html', 'utf8').replace(
    '{{ server_identity | tojson }}', JSON.stringify({name: 'robot-2.local', source: 'avahi-runtime'}));
const elements = {};
for (const id of ['server-input', 'device-input', 'speed-input', 'interface-input',
    'remote-config', 'config-validation', 'config-copy-btn', 'config-download-btn']) elements[id] = {};
let downloadLink;
let exportedBlob;
const sandbox = {
    window: {location: {hostname: '192.168.1.20'}},
    document: {
        documentElement: {setAttribute() {}},
        addEventListener() {},
        getElementById: id => elements[id],
        createElement: () => (downloadLink = {click() {this.clicked = true;}, remove() {}}),
        body: {appendChild() {}}
    },
    localStorage: {getItem: () => null},
    Blob,
    URL: {createObjectURL(blob) {exportedBlob = blob; return 'blob:test';}, revokeObjectURL() {}},
    setTimeout() {},
};
vm.createContext(sandbox);
for (const [, code] of html.matchAll(/<script>([\s\S]*?)<\/script>/g)) vm.runInContext(code, sandbox);
const run = code => vm.runInContext(code, sandbox);
run("displayedSN = '123'; lastJlinkData = {ip:'192.168.1.20', '123':{server:19011}};");
Object.assign(elements['server-input'], {value:'robot-2.local'});
Object.assign(elements['device-input'], {value:'STM32G474VE'});
Object.assign(elements['interface-input'], {value:'SWD'});
Object.assign(elements['speed-input'], {value:'8000'});
run('updateRemoteConfig()');
assert.equal(elements['config-download-btn'].disabled, false);
assert.equal(JSON.parse(elements['remote-config'].textContent).Port, 19011);
assert.equal(run('defaultServerName()[0]'), 'robot-2.local');
elements['device-input'].value = '';
run('updateRemoteConfig()');
assert.equal(elements['config-download-btn'].disabled, true);
elements['device-input'].value = 'STM32G474VE';
run("lastJlinkData['123'] = {serial:19111}; updateRemoteConfig();");
assert.equal(elements['config-download-btn'].disabled, true);
assert.equal(JSON.parse(elements['remote-config'].textContent).Port, null);
run("lastJlinkData['123'].server = 19011;");
elements['server-input'].value = 'http://robot.local:8000';
run('updateRemoteConfig()');
assert.equal(elements['config-download-btn'].disabled, true);
elements['server-input'].value = 'robot-2.local';
elements['speed-input'].value = '4000.5';
run('updateRemoteConfig()');
assert.equal(elements['config-download-btn'].disabled, true);
elements['speed-input'].value = '4000';
run('downloadRemoteConfig()');
assert.equal(downloadLink.download, 'remote-jlink.json');
assert.equal(downloadLink.clicked, true);
assert.equal(exportedBlob.type, 'application/json');
exportedBlob.text().then(text => {
    assert.ok(text.endsWith('\n'));
    assert.equal(JSON.parse(text).SpeedKHz, 4000);
    if (process.argv[2]) fs.writeFileSync(process.argv[2], text);
    console.log('Client config validation and download content OK');
});
