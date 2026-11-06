// SDK 57's query-string 7 consumer needs the default export of the fixed ESM
// decoder. Never patch an unknown package/source or silently retain the old one.
const fs = require('node:fs');
const path = require('node:path');
const {createHash} = require('node:crypto');
const {createRequire} = require('node:module');

const originalHash = 'caa3f2c8b45dfe1e91db22ae10743af68de8d96f26515132bb52485ec0f037fa';
const preparedHash = 'fc1ca6e1961ba005e554b1bc0de932d6454bf59bfaea03d02c7261dbdcafcdbd';
const hash = (source) => createHash('sha256').update(source).digest('hex');
const readJSON = (file) => JSON.parse(fs.readFileSync(file, 'utf8'));

function prepareQueryString(projectRoot, check = false) {
  const projectRequire = createRequire(path.join(projectRoot, 'package.json'));
  const consumerFile = projectRequire.resolve('query-string');
  const consumerRequire = createRequire(consumerFile);
  const decoderFile = consumerRequire.resolve('decode-uri-component');
  const consumer = readJSON(path.join(path.dirname(consumerFile), 'package.json'));
  const decoder = readJSON(path.join(path.dirname(decoderFile), 'package.json'));
  if (consumer.version !== '7.1.3' || decoder.version !== '0.5.1') {
    throw new Error('query-string adapter version drift; review before preparing dependencies');
  }
  const source = fs.readFileSync(consumerFile, 'utf8');
  if (hash(source) === preparedHash) return;
  if (hash(source) !== originalHash) {
    throw new Error('Unexpected query-string source; refusing to overwrite it');
  }
  if (check) throw new Error('query-string is not prepared; run npm run prepare:dependencies');
  const prepared = source.replace("require('decode-uri-component')", "require('decode-uri-component').default");
  if (hash(prepared) !== preparedHash) throw new Error('Unexpected prepared query-string source');
  fs.writeFileSync(consumerFile, prepared);
}

function checkDependencies() {
  prepareQueryString(path.resolve(__dirname, '..'), true);
}

module.exports = {prepareQueryString, checkDependencies};
if (require.main === module) {
  prepareQueryString(path.resolve(__dirname, '..'), process.argv.includes('--check'));
  console.log('query-string decoder adapter verified');
}
