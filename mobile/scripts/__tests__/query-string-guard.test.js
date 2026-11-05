/** @jest-environment node */
const {test, expect} = require('@jest/globals');
const fs = require('node:fs');
const path = require('node:path');
const {tmpdir} = require('node:os');
const {prepareQueryString} = require('../prepare-query-string.cjs');

function fixture(run) {
  const root = fs.mkdtempSync(path.join(tmpdir(), 'biteflow-query-'));
  const query = path.join(root, 'node_modules/query-string');
  const decoder = path.join(root, 'node_modules/decode-uri-component');
  try {
    fs.mkdirSync(query, {recursive:true}); fs.mkdirSync(decoder, {recursive:true});
    fs.writeFileSync(path.join(root, 'package.json'), '{}');
    fs.writeFileSync(path.join(query, 'package.json'), '{"name":"query-string","version":"7.1.3","main":"index.js"}');
    fs.writeFileSync(path.join(decoder, 'package.json'), '{"name":"decode-uri-component","version":"0.5.1","main":"index.js"}');
    fs.writeFileSync(path.join(decoder, 'index.js'), '');
    const original = fs.readFileSync(require.resolve('query-string'), 'utf8').replace("require('decode-uri-component').default", "require('decode-uri-component')");
    const file = path.join(query, 'index.js'); fs.writeFileSync(file, original);
    run({root, file, decoder, original});
  } finally { fs.rmSync(root, {recursive:true, force:true}); }
}

test('check-only rejects an unprepared install; preparation is idempotent', () => fixture(({root,file,original}) => {
  expect(() => prepareQueryString(root,true)).toThrow(/not prepared/);
  expect(fs.readFileSync(file,'utf8')).toBe(original);
  prepareQueryString(root);
  const ready=fs.readFileSync(file,'utf8'); expect(ready).not.toBe(original);
  prepareQueryString(root); expect(fs.readFileSync(file,'utf8')).toBe(ready);
  expect(() => prepareQueryString(root,true)).not.toThrow();
}));

test('unexpected consumer source fails closed without overwriting it', () => fixture(({root,file}) => {
  fs.appendFileSync(file,'\n// unexpected local change\n'); const before=fs.readFileSync(file,'utf8');
  expect(() => prepareQueryString(root)).toThrow(/source/);
  expect(fs.readFileSync(file,'utf8')).toBe(before);
}));

test.each(['0.4.1', '0.5.0', '0.5.2'])('decoder %s is rejected before any file is patched', (version) => fixture(({root,file,decoder,original}) => {
  fs.writeFileSync(path.join(decoder,'package.json'),JSON.stringify({version,main:'index.js'}));
  expect(() => prepareQueryString(root)).toThrow(/version/);
  expect(fs.readFileSync(file,'utf8')).toBe(original);
}));
