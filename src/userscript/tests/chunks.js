// Тест резки на чанки (TTS-6). Юзерскрипт — один файл и живёт в браузере,
// поэтому тест не импортирует его, а вырезает из живого текста секции
// «1. Константы» и «4. Резка на чанки» и выполняет их в Node. Значит тест
// проверяет ровно тот код, который поедет пользователю, и ломается сразу,
// если секции переименуют.
//
// Запуск: `node userscript/tests/chunks.js` (из любого места)
const fs = require('fs');
const path = require('path');
const src = fs.readFileSync(path.join(__dirname, '..', 'skaz.user.js'), 'utf8');

function section(from, to) {
  const a = src.indexOf(from);
  const b = src.indexOf(to);
  if (a < 0 || b < 0) throw new Error('не нашёл секцию ' + from);
  return src.slice(a, b);
}

const code = section('// ==== 1. Константы', '// ==== 2. Настройки')
  + section('// ==== 4. Резка на чанки', '// ==== 5. Подсветка')
  + '\nmodule.exports = { chunkText, splitSentences, budget, segments, PAUSE_BLOCK, PAUSE_HEADING, MERGE_SHORT };\n';

const module_ = { exports: {} };
new Function('module', code)(module_);
const { chunkText, budget, PAUSE_BLOCK, PAUSE_HEADING } = module_.exports;

function show(title, text) {
  const spans = chunkText(text);
  console.log('\n=== ' + title + ' — ' + text.length + ' знаков → ' + spans.length + ' чанков');
  spans.forEach(([s, e], i) => {
    const t = text.slice(s, e);
    console.log(`  ${String(i + 1).padStart(2)} [${String(e - s).padStart(3)} зн, бюджет ${String(budget(text, s, e)).padStart(4)}] ${t}`);
  });
  return spans;
}

const T1 = 'А. С. Пушкин родился в Москве. Его отец, Сергей Львович, был отставным майором. '
  + '— Я… не знаю, — сказал он тихо. «Мы уходим.» Дальше был только снег. '
  + 'Работы велись в 1867 г. и позже, в 1901 г. тоже. Всё это и т.д. и т.п. Конец.';

const T2 = 'Он шёл по узкой улице, которая петляла между старыми домами с облупившейся '
  + 'штукатуркой, мимо закрытых лавок и тёмных подворотен, где пахло сыростью и кошками, '
  + 'и думал о том, что завтра всё изменится, потому что иначе быть уже не могло, '
  + 'ведь письмо пришло вчера вечером, и в нём было сказано ровно то, чего он боялся '
  + 'все эти долгие месяцы ожидания.';

const T3 = 'В 1867 году было продано 1500000 акров за 7200000 долларов, а в 1901 году — '
  + 'ещё 3400000 акров за 12500000 долларов, и в 1917 году сумма достигла 45000000.';

const T4 = 'Да. Нет. Может быть. Я не знаю точно, что именно произошло той ночью в старом доме.';

const T5 = 'Он открыл файл config.json в редакторе VS Code и нажал Ctrl+S. '
  + 'Потом проверил HTML и API через Wi-Fi на Windows.';

const T6 = 'Одно длинное предложение без единого знака препинания внутри которое тянется '
  + 'и тянется и тянется и никак не может закончиться потому что автор забыл про запятые '
  + 'совершенно и полностью и абсолютно и это продолжается уже очень долго и утомительно';

const a1 = show('T1 инициалы, прямая речь, сокращения', T1);
const a2 = show('T2 длинное предложение', T2);
const a3 = show('T3 числа (бюджет нормализации)', T3);
const a4 = show('T4 короткие реплики', T4);
const a5 = show('T5 латиница', T5);
const a6 = show('T6 без пунктуации', T6);

console.log('\n--- проверки ---');
function check(name, ok, extra) {
  console.log((ok ? 'OK   ' : 'FAIL ') + name + (extra === undefined ? '' : '  ' + extra));
  if (!ok) process.exitCode = 1;
}

function joined(text, spans) {
  return spans.map(([s, e]) => text.slice(s, e)).join(' ');
}

// 1. ничего не потеряно: склейка чанков совпадает с исходником по буквам
function letters(s) { return s.replace(/[^\p{L}\p{N}]/gu, ''); }
for (const [name, text, spans] of [['T1', T1, a1], ['T2', T2, a2], ['T3', T3, a3],
                                   ['T4', T4, a4], ['T5', T5, a5], ['T6', T6, a6]]) {
  check(name + ': текст не потерян', letters(joined(text, spans)) === letters(text));
}

// 2. первый чанк короткий
for (const [name, text, spans] of [['T1', T1, a1], ['T2', T2, a2], ['T3', T3, a3],
                                   ['T4', T4, a4], ['T5', T5, a5], ['T6', T6, a6]]) {
  check(name + ': первый чанк <= 121', spans[0][1] - spans[0][0] <= 121, spans[0][1] - spans[0][0]);
}

// 3. ни один чанк не разорван посреди инициала или сокращения
const bad = a1.filter(([s, e]) => /(?:^|\s)(?:[А-ЯA-Z]|т\.[дп]|г|см)\.$/.test(T1.slice(s, e)));
check('T1: нет обрыва на инициале/сокращении', bad.length === 0, bad.map(([s, e]) => T1.slice(s, e)));

// 4. бюджет нормализации выдержан
for (const [name, text, spans] of [['T1', T1, a1], ['T3', T3, a3], ['T5', T5, a5]]) {
  const over = spans.filter(([s, e]) => budget(text, s, e) > 700);
  check(name + ': бюджет <= 700', over.length === 0, over.length);
}

// 5. длина чанка в пределах
for (const [name, text, spans] of [['T1', T1, a1], ['T2', T2, a2], ['T3', T3, a3],
                                   ['T4', T4, a4], ['T5', T5, a5], ['T6', T6, a6]]) {
  const over = spans.filter(([s, e], i) => e - s > (i === 0 ? 121 : 251));
  check(name + ': чанки <= 250', over.length === 0, over.map(([s, e]) => e - s));
}

// 6. нет пустых и чисто-пунктуационных чанков
for (const [name, text, spans] of [['T1', T1, a1], ['T4', T4, a4]]) {
  check(name + ': нет мусорных чанков', spans.every(([s, e]) => /[\p{L}\p{N}]/u.test(text.slice(s, e))));
}

// 7. большой текст: скорость и число чанков
const big = (T1 + ' ' + T2 + ' ' + T3 + ' ') .repeat(40);
const t0 = Date.now();
const spansBig = chunkText(big);
console.log(`\nбольшой текст: ${big.length} знаков → ${spansBig.length} чанков за ${Date.now() - t0} мс`);
check('большой: текст не потерян', letters(joined(big, spansBig)) === letters(big));
check('большой: режется быстрее 200 мс', Date.now() - t0 < 200);
const avg = spansBig.reduce((a, [s, e]) => a + (e - s), 0) / spansBig.length;
console.log('средняя длина чанка: ' + avg.toFixed(1));

// --- блоки (TTS-7): абзацы режутся порознь, на стыке появляется пауза ---
//
// Сборщик из секции 3 отдаёт текст плюс границы блоков ровно в таком виде:
// абзацы склеены пробелом, каждый блок знает своё начало и конец.
function paged(parts) {
  let text = '';
  const blocks = [];
  for (const p of parts) {
    if (text.length) text += ' ';
    const s = text.length;
    text += p.t;
    blocks.push({ s, e: text.length, heading: !!p.h });
  }
  return { text, blocks };
}

const PAGE = paged([
  { t: 'Глава седьмая', h: true },
  { t: 'Он вышел на улицу и огляделся по сторонам. Улица была пуста, только ветер гонял по ней обрывки старых газет и жёлтые листья.' },
  { t: '— Ты пришёл' },
  { t: '— Да' },
  { t: 'Она стояла у самой двери, не решаясь ни войти, ни уйти, и смотрела куда-то мимо него, в глубину тёмного коридора.' },
]);

const pageSpans = show('PAGE страница из пяти блоков', PAGE.text);
const blockSpans = chunkText(PAGE.text, PAGE.blocks);
console.log('\n=== те же блоки с границами — ' + blockSpans.length + ' чанков');
blockSpans.forEach(([s, e, pause], i) => {
  console.log(`  ${String(i + 1).padStart(2)} [${String(e - s).padStart(3)} зн, пауза ${String(pause).padStart(3)}] ${PAGE.text.slice(s, e)}`);
});

console.log('\n--- проверки блоков ---');
check('блоки: текст не потерян', letters(joined(PAGE.text, blockSpans)) === letters(PAGE.text));
check('блоки: без границ текст режется иначе', pageSpans.length !== blockSpans.length
  || pageSpans.some(([s, e], i) => s !== blockSpans[i][0] || e !== blockSpans[i][1]));

// 1. ни один чанк не пересекает границу блока (кроме склеенных коротышей)
const boundaries = PAGE.blocks.slice(1).map((b) => b.s);
const crossing = blockSpans.filter(([s, e]) => boundaries.some((b) => b > s && b < e));
// «— Ты пришёл» и «— Да» короче MERGE_SHORT и склеиваются намеренно
const allowed = new Set([PAGE.blocks[3].s]);
check('блоки: чанк не перепрыгивает из абзаца в абзац',
  crossing.every(([s, e]) => boundaries.filter((b) => b > s && b < e).every((b) => allowed.has(b))),
  crossing.map(([s, e]) => PAGE.text.slice(s, e)));

// 2. пауза стоит ровно на последнем чанке блока и нигде больше
const paused = blockSpans.filter(([, , p]) => p > 0);
check('блоки: пауза только на стыках', paused.every(([, e]) =>
  PAGE.blocks.some((b) => b.e === e)), paused.length);
check('блоки: в конце паузы нет', blockSpans[blockSpans.length - 1][2] === 0);

// 3. заголовок — отдельный чанк с долгой паузой, он не склеен с абзацем
const head = blockSpans[0];
check('блоки: заголовок отдельным чанком', PAGE.text.slice(head[0], head[1]) === 'Глава седьмая',
  PAGE.text.slice(head[0], head[1]));
check('блоки: после заголовка пауза длиннее', head[2] === PAUSE_HEADING, head[2]);
check('блоки: между абзацами обычная пауза',
  blockSpans.some(([, , p]) => p === PAUSE_BLOCK));

// 4. короткие реплики склеены в один чанк, а не в два запроса
check('блоки: короткие реплики склеены',
  blockSpans.some(([s, e]) => /Ты пришёл.*Да/s.test(PAGE.text.slice(s, e))),
  blockSpans.map(([s, e]) => PAGE.text.slice(s, e)).find((t) => t.includes('Ты пришёл')));

// 5. большой текст с блоками: скорость
const bigParts = [];
for (let i = 0; i < 120; i++) {
  bigParts.push({ t: 'Часть ' + (i + 1), h: true });
  bigParts.push({ t: T1 });
  bigParts.push({ t: T2 });
  bigParts.push({ t: T3 });
}
const BIG = paged(bigParts);
const t1 = Date.now();
const bigBlockSpans = chunkText(BIG.text, BIG.blocks);
const spent = Date.now() - t1;
console.log(`\nбольшой текст с блоками: ${BIG.text.length} знаков, ${BIG.blocks.length} блоков → ${bigBlockSpans.length} чанков за ${spent} мс`);
check('большой с блоками: текст не потерян', letters(joined(BIG.text, bigBlockSpans)) === letters(BIG.text));
check('большой с блоками: режется быстрее 200 мс', spent < 200, spent);
