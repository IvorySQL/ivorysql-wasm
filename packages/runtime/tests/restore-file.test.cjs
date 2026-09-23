const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const { V86 } = require('../lib/libv86.js');

const html = fs.readFileSync(path.join(__dirname, '../index.html'), 'utf8');
const startup = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)]
  .map(match => match[1]).find(script => script.includes('window.onload'));

function setup(running = true) {
  const elements = new Map();
  const events = [];
  const listeners = new Map();
  let reader;
  // Exercise the bundled V86 stop/restore/run methods with a controlled CPU.
  // No guest image is booted by these lifecycle tests.
  const emulator = Object.create(V86.prototype);
  emulator.cpu_is_running = running;
  emulator.add_listener = (name, callback) => listeners.set(name, callback);
  emulator.remove_listener = name => listeners.delete(name);
  emulator.v86 = {
    stop() { events.push('stop requested'); },
    restore_state(bytes) { events.push(['restore', bytes]); },
    run() { events.push('run'); },
  };
  const context = {
    window: {}, URL, TextEncoder, console,
    document: {
      location: 'http://localhost/',
      getElementById(id) {
        if (!elements.has(id)) elements.set(id, { blur() {} });
        return elements.get(id);
      },
      getElementsByClassName() { return []; },
    },
    V86: function () { return emulator; },
    FileReader: class {
      constructor() { reader = this; }
      readAsArrayBuffer() {}
    },
  };
  vm.runInNewContext(startup, context);
  context.window.onload();
  const input = elements.get('restore_file');
  input.files = [{}];
  input.onchange();
  return {
    reader, events,
    stopped() {
      emulator.cpu_is_running = false;
      listeners.get('emulator-stopped')();
    },
  };
}

test('waits for the emulator-stopped event before restoring and running', async () => {
  const fixture = setup();
  const bytes = new ArrayBuffer(4);
  const restored = fixture.reader.onload({ target: { result: bytes } });
  await Promise.resolve();
  assert.deepEqual(fixture.events, ['stop requested']);
  fixture.stopped();
  await restored;
  assert.deepEqual(fixture.events, ['stop requested', ['restore', bytes], 'run']);
});

test('does not stop the current session while the selected file is unreadable', () => {
  const fixture = setup();
  // A failed/aborted FileReader does not dispatch load.
  assert.deepEqual(fixture.events, []);
});

test('restores an already stopped emulator without waiting for another stop event', async () => {
  const fixture = setup(false);
  const bytes = new ArrayBuffer(4);
  await fixture.reader.onload({ target: { result: bytes } });
  assert.deepEqual(fixture.events, [['restore', bytes], 'run']);
});
