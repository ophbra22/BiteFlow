/** @jest-environment node */
const {test, expect} = require('@jest/globals');
const {spawnSync} = require('node:child_process');
const path = require('node:path');

test('the real query consumer also loads through the Expo Jest transform', () => {
  expect(require('query-string').parse('name=%D7%A4%D7%99%D7%AA%D7%94')).toEqual({name:'פיתה'});
});

function parse(query) {
  // A separate process bounds the vulnerable decoder's CPU/stack exposure.
  const result = spawnSync(process.execPath, ['--max-old-space-size=128', '-e',
    'const q=require("query-string"); console.log(JSON.stringify(q.parse(require("node:fs").readFileSync(0,"utf8"))));'],
  {cwd:path.resolve(__dirname, '../..'), encoding:'utf8', input:query, timeout:3000});
  expect(result.error).toBeUndefined();
  expect(result.status).toBe(0);
  return JSON.parse(result.stdout);
}

test('navigation query parsing finishes for a long malformed percent run', () => {
  const malformed = '%80'.repeat(5000);
  expect(parse('food='+malformed)).toEqual({food:malformed});
});

test('navigation preserves Hebrew, plus/encoded-plus, repeated keys and empty values', () => {
  expect(parse('name=%D7%A4%D7%99%D7%AA%D7%94&space=a+b&plus=a%2Bb&item=1&item=2&empty=&flag'))
    .toEqual({name:'פיתה', space:'a b', plus:'a+b', item:['1','2'], empty:'', flag:null});
});

test('partially malformed navigation values preserve literal bytes and valid UTF-8', () => {
  expect(parse('food=%80%D7%A4&bad=%ZZ&short=%E2%82')).toEqual({food:'%80פ', bad:'%ZZ', short:'%E2%82'});
});

test('navigation query parsing bounds many distinct percent runs with a malformed suffix', () => {
  // GHSA-qr28-fpjm-wq7f: each distinct run used to cause another full-string scan.
  // Use stdin rather than argv to exercise a large input on Windows as well.
  const runs = Array.from({length:32000}, (_, i) =>
    `%${Math.floor(i / 256).toString(16).padStart(2, '0')}%${(i % 256).toString(16).padStart(2, '0')}x`);
  const value = parse('value=' + runs.join('') + '%zz').value;
  expect(value.endsWith('%zz')).toBe(true);
});
test('Expo default and bundled navigation paths preserve deep-link query values', () => {
  const query = 'name=%D7%A4%D7%99%D7%AA%D7%94&space=a+b&plus=a%2Bb&item=1&item=2&empty=';
  const expected = {name:'פיתה', space:'a b', plus:'a+b', item:['1','2'], empty:''};
  const {parseQueryParams} = require('expo-router/build/fork/getStateFromPath-forks');
  expect(parseQueryParams('/review?' + query, {name:'review'})).toEqual(expected);
  const {getStateFromPath} = require('expo-router/build/react-navigation/core/getStateFromPath');
  const state = getStateFromPath('/review?' + query, {screens:{review:'review'}});
  expect(state.routes[0].params).toEqual(expected);
});
