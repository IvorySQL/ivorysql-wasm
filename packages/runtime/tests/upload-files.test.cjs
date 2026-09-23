const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../index.html'), 'utf8');
const startup = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)]
  .map(match => match[1]).find(script => script.includes('window.onload'));

async function upload(files) {
  const elements = new Map();
  const writes = [];
  const reads = [];
  const context = {
    window: {}, URL, TextEncoder, console,
    document: {
      location: 'http://localhost/',
      getElementById(id) {
        if (!elements.has(id)) elements.set(id, {});
        return elements.get(id);
      },
      getElementsByClassName() { return []; },
    },
    // Only record the filesystem boundary; no VM image is booted by this test.
    V86: class {
      add_listener() {}
      create_file(name, bytes) { writes.push({ name, bytes: Buffer.from(bytes) }); }
    },
    // Node Blob provides the same UTF-8 text conversion and raw byte reads.
    FileReader: class {
      readAsText(blob) { this.read(blob.text()); }
      readAsArrayBuffer(blob) { this.read(blob.arrayBuffer()); }
      read(result) {
        reads.push(result.then(value => this.onload({ target: { result: value } })));
      }
    },
  };
  vm.runInNewContext(startup, context);
  context.window.onload();
  elements.get('upload_files').onchange({ target: { files } });
  await Promise.all(reads);
  return writes;
}

function file(name, bytes) {
  return Object.assign(new Blob([bytes]), { name });
}

test('preserves binary bytes, including NUL and invalid UTF-8', async () => {
  const bytes = Buffer.from([0x50, 0x47, 0x44, 0x4d, 0x50, 0, 0xff, 0xfe, 0x80, 0xc3]);
  assert.deepEqual(await upload([file('backup.dump', bytes)]), [
    { name: '/backup.dump', bytes },
  ]);
});

test('preserves the UTF-8 BOM and non-ASCII SQL text', async () => {
  const bytes = Buffer.from('\uFEFFSELECT \'中文😀\';\r\n');
  assert.deepEqual(await upload([file('query.sql', bytes)]), [
    { name: '/query.sql', bytes },
  ]);
});

test('keeps multiple file names and contents separate, including empty files', async () => {
  const first = Buffer.from('SELECT 1;\n');
  const second = Buffer.from([0, 255, 128]);
  const writes = await upload([
    file('first.sql', first), file('second.bin', second), file('empty', Buffer.alloc(0)),
  ]);
  assert.deepEqual(writes.sort((a, b) => a.name.localeCompare(b.name)), [
    { name: '/empty', bytes: Buffer.alloc(0) },
    { name: '/first.sql', bytes: first },
    { name: '/second.bin', bytes: second },
  ]);
});
