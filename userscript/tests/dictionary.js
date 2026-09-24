// node userscript/tests/dictionary.js — проверка импорта без доступа к пользовательскому словарю.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../skaz.user.js'), 'utf8');
const between = (start, end) => source.slice(source.indexOf(start), source.indexOf(end));
let rows = [], message = '', saved = null, invalidateCount = 0;
const render = entries => { rows = Object.entries(entries).map(([key, value]) => [key, value].map(value => ({value}))); };
const context = {
  TextEncoder,
  panel: {dictRevision: 0, dictDirty: false, root: {
    querySelectorAll: () => rows.map(inputs => ({querySelectorAll: () => inputs})),
  }},
  renderDict: render,
  setSettingsMessage: (_, text) => { message = text; },
  baseUrl: () => 'http://test', GM_getValue: () => 'test-token',
  gmJson: async (method, url, data) => { saved = JSON.parse(JSON.stringify(data)); },
  invalidateFutureAudio: () => { invalidateCount++; },
};
vm.createContext(context);
vm.runInContext(
  between('  function dictEdited()', '  function renderDict(') +
  between('  async function loadDict()', '  function dictEdited()') +
  between('  function readDictRows()', '  function newerVersion('), context);
const file = text => ({size: new TextEncoder().encode(text).length, text: async () => text});
const plain = value => JSON.parse(JSON.stringify(value));

async function run() {
  assert.deepEqual(plain(context.parseDictImport('\uFEFF{"Фердинанд":"Фердин+анд"}')), {Фердинанд:'Фердин+анд'});
  assert.deepEqual(plain(context.parseDictImport('{"entries":{"Цунаде":"Цун+адэ"}}')), {Цунаде:'Цун+адэ'});
  for (const invalid of ['[]', 'null', '"text"', '{bad', '{"x":1}', '{"":"value"}', '{"x":""}']) {
    assert.throws(() => context.parseDictImport(invalid));
  }
  assert.throws(() => context.parseDictImport(' '.repeat(65537)));
  render({Цунаде:'Цун+адэ', Фердинанд:'Ф+ердинанд'});
  await context.importDictFile(file('{"фердинанд":"Фердин+анд","Шарлотта":"Шарл+отта"}'));
  assert.deepEqual(plain(context.readDictRows()), {Цунаде:'Цун+адэ', фердинанд:'Фердин+анд', Шарлотта:'Шарл+отта'});
  assert.equal(saved, null, 'Import must wait for explicit save');
  assert.match(message, /Импортировано 2/);
  const before = plain(context.readDictRows());
  await context.importDictFile(file('{bad'));
  assert.deepEqual(plain(context.readDictRows()), before, 'Bad import preserves existing entries');
  await context.saveDict();
  assert.deepEqual(saved, before);
  assert.equal(context.panel.dictDirty, false);
  assert.equal(invalidateCount, 1);

  render({});
  await context.importDictFile(file('{"__proto__":"слово"}'));
  assert.equal(Object.hasOwn(context.readDictRows(), '__proto__'), true);
  assert.equal(context.readDictRows().__proto__, 'слово');

  // GET был начат до правки: его ответ не должен удалить введённую строку.
  context.panel.dictDirty = false;
  let deliver;
  context.gmJson = () => new Promise(resolve => { deliver = resolve; });
  const loading = context.loadDict();
  render({Новое:'Н+овое'}); context.dictEdited();
  deliver({entries:{Старое:'Ст+арое'}});
  await loading;
  assert.deepEqual(plain(context.readDictRows()), {Новое:'Н+овое'});
  console.log('OK: JSON formats, validation, merge, explicit save, prototype keys, late server response');
}
run().catch(error => { console.error(error); process.exitCode = 1; });
