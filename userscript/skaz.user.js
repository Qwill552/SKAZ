// ==UserScript==
// @name         SKAZ
// @namespace    https://github.com/Qwill552/SKAZ
// @version      1.0.1
// @updateURL    https://github.com/Qwill552/SKAZ/releases/latest/download/skaz.user.js
// @downloadURL  https://github.com/Qwill552/SKAZ/releases/latest/download/skaz.user.js
// @description  Озвучивает выделенный текст или всю страницу локальным Silero
// @match        *://*/*
// @match        file:///*
// @noframes
// @run-at       document-idle
// @grant        GM_xmlhttpRequest
// @grant        GM_setValue
// @grant        GM_getValue
// @grant        GM_registerMenuCommand
// @grant        GM_notification
// @connect      localhost
// @connect      127.0.0.1
// @connect      api.github.com
// @require      https://raw.githubusercontent.com/Tampermonkey/utils/refs/heads/main/requires/gh_2215_make_GM_xhr_more_parallel_again.js
// ==/UserScript==

// Файл держится секциями с разделителями-комментариями: разбить на модули
// через @require нельзя — раздача одна, скрипт один.
//
//   1. Константы
//   2. Настройки и хоткей
//   3. Извлечение текста с привязкой к DOM
//   4. Резка на чанки
//   5. Подсветка чанка и слова
//   6. Прокрутка вслед за чтением
//   7. Панель
//   8. Плеер: состояния, очередь запросов, очередь воспроизведения
//   9. Ввод
//  10. Меню Tampermonkey

(function () {
  'use strict';

  // ==== 1. Константы =====================================================

  const DEFAULT_BASE_URL = 'http://127.0.0.1:8756';
  const SCRIPT_VERSION = '1.0.1';
  const GITHUB_REPO = 'Qwill552/SKAZ';
  const DEFAULT_VOICE = 'baya';
  const DEFAULT_HOTKEY = { code: 'KeyT', alt: true, ctrl: false, shift: false, meta: false };

  // Глубина префетча. 2 — из RTF, замеренного в TTS-1: синтез быстрее
  // реального времени в 16 раз, два чанка вперёд успевают с запасом.
  const DEFAULT_PREFETCH = 2;

  // Первый чанк короткий нарочно: между хоткеем и первым звуком должно
  // пройти меньше секунды, а дальше разницы в размере уже не слышно.
  const FIRST_CHUNK_MAX = 120;
  const FIRST_CHUNK_MIN = 60;   // «Он шёл по узкой улице,» — законченная мысль, а не обрубок
  const MAX_CHUNK = 250;
  const MIN_PIECE = 100;   // нижняя граница куска при резке длинного предложения
  const MERGE_SHORT = 25;  // «— Да.» отдельным запросом не гоняем, клеим к следующему

  // Предохранитель /tts — 800 знаков ПОСЛЕ нормализации (TTS-4 раскрывает
  // числа: «1867» превращается в 33 знака). Чанк в 250 сырых знаков обычно
  // укладывается, но абзац из одних дат — нет. Оцениваем разбухание здесь,
  // до отправки: 413 посреди чтения — это баг чанкинга, а не нормальный ответ.
  const BUDGET_LIMIT = 700;
  const DIGIT_COST = 9;    // «7» → «семь», «1867» → «тысяча восемьсот шестьдесят седьмом»
  const LATIN_COST = 2;    // «HTML» → «эйч-ти-эм-эль»

  const RETRY_DELAY = 1000;
  const REQUEST_TIMEOUT = 45000;
  const MAX_FAILURES = 3;
  const SEEK_DEBOUNCE = 160;   // Alt+→ десять раз подряд не должен устроить шторм запросов
  const OWN_SCROLL_WINDOW = 5000;

  const RATE_MIN = 0.5;
  const RATE_MAX = 2.5;
  const RATE_STEP = 0.1;

  const HIGHLIGHT_NAME = 'skaz-chunk';
  const WORD_HIGHLIGHT_NAME = 'skaz-word';

  // Заголовок с таймингами слов (TTS-7A). Тело ответа остаётся голым WAV:
  // multipart пришлось бы разбирать руками из arraybuffer, а заголовок
  // читается одной регуляркой и весит на предложение меньше килобайта.
  const TIMINGS_HEADER_RE = /^x-skaz-timings:[ \t]*(\S+)/im;

  const MODIFIER_CODES = new Set([
    'AltLeft', 'AltRight', 'ControlLeft', 'ControlRight',
    'ShiftLeft', 'ShiftRight', 'MetaLeft', 'MetaRight',
  ]);
  const KNOWN_CONFLICTS = [
    { code: 'KeyT', ctrl: true, alt: false, shift: false, meta: false },
    { code: 'KeyW', ctrl: true, alt: false, shift: false, meta: false },
    { code: 'KeyN', ctrl: true, alt: false, shift: false, meta: false },
    { code: 'F5', ctrl: false, alt: false, shift: false, meta: false },
  ];

  // Сокращения с точкой. TTS-4 их уже раскрывает на сервере, но юзерскрипт
  // режет текст ДО отправки и про раскрытие не знает — список нужен и здесь.
  const ABBREV = new Set([
    'т.д.', 'т.п.', 'т.е.', 'т.к.', 'т.н.', 'н.э.', 'р.х.',
    'г.', 'гг.', 'в.', 'вв.', 'см.', 'ср.', 'стр.', 'рис.', 'табл.', 'гл.',
    'ул.', 'пр.', 'пер.', 'наб.', 'д.', 'корп.', 'кв.', 'обл.', 'респ.',
    'др.', 'пр.', 'проф.', 'акад.', 'им.', 'напр.', 'ок.', 'св.',
    'руб.', 'коп.', 'тыс.', 'экз.', 'шт.', 'мин.', 'сек.', 'ч.',
    'ст.', 'п.', 'пп.', 'мл.', 'англ.', 'лат.', 'греч.', 'яп.',
  ]);

  // Сокращения, которыми предложение обычно и кончается. Для них заглавная
  // буква следом — настоящая граница: «…и т.п. Он открыл файл» это два
  // предложения. Для остальных заглавная ничего не значит («в 1867 г. Россия
  // продала…» — одно), поэтому список короткий и расширять его наугад нельзя.
  const ABBREV_TERMINAL = new Set(['т.д.', 'т.п.', 'др.']);

  const TERMINATORS = '.!?…';
  const CLOSERS = '»"\'’”)]}';
  const SOFT_BREAKS = ',;:—–';

  // Пауза на стыке блоков. Между предложениями внутри абзаца её нет вовсе
  // (следующий чанк играет по ended предыдущего), поэтому даже треть секунды
  // слышно отчётливо. После заголовка — вдвое длиннее.
  const PAUSE_BLOCK = 380;
  const PAUSE_HEADING = 760;

  // Блочные теги: между двумя такими текст не склеивается в одно слово.
  // Считаем по именам тегов, а не по getComputedStyle — тот на главе в
  // тысячу узлов стоит заметных миллисекунд, а ошибается редкая вёрстка.
  const BLOCK_TAGS = new Set([
    'ADDRESS', 'ARTICLE', 'ASIDE', 'BLOCKQUOTE', 'DD', 'DIV', 'DL', 'DT',
    'FIELDSET', 'FIGCAPTION', 'FIGURE', 'FOOTER', 'FORM', 'H1', 'H2', 'H3',
    'H4', 'H5', 'H6', 'HEADER', 'HR', 'LI', 'MAIN', 'NAV', 'OL', 'P', 'PRE',
    'SECTION', 'TABLE', 'TBODY', 'TD', 'TFOOT', 'TH', 'THEAD', 'TR', 'UL',
  ]);

  const HEADING_TAGS = new Set(['H1', 'H2', 'H3', 'H4', 'H5', 'H6']);

  // Не текст ни при каких условиях — выбрасываем и на выделении тоже.
  const HARD_SKIP = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE']);

  // Выбрасываем только при чтении страницы целиком. На выделении не трогаем:
  // раз человек выделил код руками — значит хочет услышать код.
  const PAGE_SKIP = new Set([
    'CODE', 'PRE', 'KBD', 'SAMP', 'VAR', 'SUP', 'MATH',
    'SVG', 'CANVAS', 'IMG', 'IFRAME', 'OBJECT', 'EMBED', 'VIDEO', 'AUDIO',
    'TEXTAREA', 'INPUT', 'SELECT', 'OPTION', 'BUTTON', 'LABEL',
    'NAV', 'HEADER', 'FOOTER', 'ASIDE', 'FIGCAPTION', 'FORM', 'DIALOG',
  ]);

  // Мусор по классу и идентификатору: теги выше ловят разметку, а этот список —
  // соглашения. Пополняется по мере встречи новых сайтов. Расширять осторожно:
  // лишнее слово здесь молча съедает кусок статьи, и найти это трудно.
  const JUNK_RE = new RegExp(
    '(?:^|[\\s_-])(?:' + [
      'comments?', 'disqus', 'sidebar', 'side', 'related', 'recommend',
      'share', 'sharing', 'social', 'promo', 'banner', 'advert', 'ads', 'adv',
      'reklama', 'popup', 'modal', 'overlay', 'breadcrumbs?', 'pagination',
      'pager', 'menu', 'navbar', 'navigation', 'nav', 'toc', 'navbox',
      'infobox', 'metadata', 'editsection', 'thumbcaption', 'caption',
      'cookie', 'subscribe', 'newsletter', 'footer', 'copyright', 'rating',
      'vote', 'sr-only', 'visually-hidden', 'screen-reader', 'skip-link',
      'hatnote', 'reflist', 'refbegin', 'catlinks', 'printfooter', 'mw-jump',
    ].join('|') + ')(?:[\\s_-]|\\d|$)', 'i'
  );

  // Явная разметка статьи — первый и самый надёжный источник.
  const CONTAINER_SELECTORS = [
    'article', '[itemprop="articleBody"]', 'main', '[role="main"]',
  ];

  // Частые классы и идентификаторы. Тоже пополняется по мере встречи сайтов.
  const CONTAINER_HINTS = [
    '.post-content', '.entry-content', '.article-body', '.article__body',
    '.article-content', '.post__text', '.tm-article-body', '.story-body',
    '#mw-content-text', '.mw-parser-output', '.chapter-content', '.reader-content',
    '.post', '.chapter', '#content', '.content', '.text',
  ];

  // Что вообще может быть контейнером на шаге скоринга.
  const CONTAINER_TAGS = new Set([
    'DIV', 'SECTION', 'ARTICLE', 'MAIN', 'BODY', 'TD', 'BLOCKQUOTE', 'DL', 'UL', 'OL',
  ]);

  const MIN_CONTAINER_TEXT = 200;   // меньше — это не статья, а подпись
  const MAX_LINK_DENSITY = 0.4;     // больше — это список ссылок, а не текст
  const NARROW_KEEP = 0.9;          // сужаемся, только если текст почти весь остался
  const NAV_LINK_DENSITY = 0.75;    // столько ссылок в блоке — это меню, а не абзац

  const WS = /\s/;
  const NONSPACE = /\S/;
  const UPPER = /\p{Lu}/u;
  const LETTER_OR_DOT = /[\p{L}.]/u;
  const LATIN = /[A-Za-z]/;

  // ==== 2. Настройки и хоткей ============================================

  function baseUrl() { return GM_getValue('baseUrl', DEFAULT_BASE_URL); }
  function voice() { return GM_getValue('voice', DEFAULT_VOICE); }
  function prefetch() { return Math.min(4, Math.max(1, Number(GM_getValue('prefetch', DEFAULT_PREFETCH)) || 2)); }

  function loadHotkey() {
    const stored = GM_getValue('hotkey', null);
    if (stored && stored.code) return stored;
    return DEFAULT_HOTKEY;
  }

  function ensureToken() {
    const token = GM_getValue('token', '');
    if (!token) { openSettings(); setNote('Вставьте ключ или откройте /setup на сервере'); }
    return token;
  }

  function configureServer() {
    openSettings();
  }

  function codeLabel(code) {
    if (code.startsWith('Key')) return code.slice(3);
    if (code.startsWith('Digit')) return code.slice(5);
    return code;
  }

  function describeHotkey(combo) {
    const parts = [];
    if (combo.ctrl) parts.push('Ctrl');
    if (combo.alt) parts.push('Alt');
    if (combo.shift) parts.push('Shift');
    if (combo.meta) parts.push('Win');
    parts.push(codeLabel(combo.code));
    return parts.join('+');
  }

  function isKnownConflict(combo) {
    return KNOWN_CONFLICTS.some((c) =>
      c.code === combo.code && c.ctrl === combo.ctrl && c.alt === combo.alt &&
      c.shift === combo.shift && c.meta === combo.meta
    );
  }

  function openHotkeyCapture() {
    if (!panel.settings) openSettings();
    if (panel.capturing) return;
    panel.capturing = true;
    const overlay = document.createElement('div');
    overlay.textContent = 'Нажми сочетание, Escape — отмена';
    Object.assign(overlay.style, {
      position: 'absolute', top: '0', right: '0',
      background: '#222', color: '#fff', padding: '12px 20px', borderRadius: '6px',
      fontSize: '14px', fontFamily: 'sans-serif', zIndex: 2,
      boxShadow: '0 2px 10px rgba(0,0,0,0.4)',
    });
    panel.root.appendChild(overlay);

    function finish() {
      document.removeEventListener('keydown', handler, true);
      overlay.remove();
      panel.capturing = false;
    }

    function handler(e) {
      if (e.code === 'Escape') {
        e.preventDefault();
        finish();
        return;
      }
      if (MODIFIER_CODES.has(e.code)) return;
      e.preventDefault();
      e.stopPropagation();
      const combo = { code: e.code, alt: e.altKey, ctrl: e.ctrlKey, shift: e.shiftKey, meta: e.metaKey };
      if (!combo.alt && !combo.ctrl && !combo.meta) {
        GM_notification('Нужен хотя бы один модификатор: Alt, Ctrl или Win');
        finish();
        return;
      }
      GM_setValue('hotkey', combo);
      let msg = `Горячая клавиша: ${describeHotkey(combo)}`;
      if (isKnownConflict(combo)) msg += '. Браузер может перехватить это сочетание раньше страницы.';
      GM_notification(msg);
      if (panel.els) panel.els.hotkey.textContent = describeHotkey(combo);
      finish();
    }

    document.addEventListener('keydown', handler, true);
  }

  // ==== 3. Извлечение текста с привязкой к DOM ===========================
  //
  // Отдаём не строку и не [{text, range}] на блок, как предполагало ТЗ, а одну
  // структуру: текст, карту «символ → (текстовый узел, смещение)» и список
  // блоков. Range на целый блок подсветке не годится — подсвечивается чанк, а
  // он мельче блока; из карты же Range строится на любой отрезок. Блоки при
  // этом не теряются: они приезжают списком, режутся порознь (секция 4), и
  // чанк никогда не перепрыгивает из абзаца в абзац, а на стыке слышна пауза.
  //
  // Пробелы схлопываются на лету, одним проходом, и схлопнутый пробел получает
  // координату следующего за ним настоящего символа — так границы чанков всегда
  // попадают на видимый текст, а не в пустоту между узлами.
  //
  // Один и тот же сборщик работает и на выделении, и на странице целиком:
  // выделение — это просто «весь документ» из одного блока, и дальше по
  // конвейеру ветвления нет.

  // --- 3.1 сборщик ---

  function isOurPanel(node) {
    return !!(panel.host && (node === panel.host || panel.host.contains(node)));
  }

  function newDoc() {
    return {
      text: '', nodes: [], mapNode: null, mapOff: null, blocks: [],
      chars: [], mn: [], mo: [],
      pendingSpace: false, blockEl: undefined, blockStart: 0, blockHead: false, forceBlock: false,
    };
  }

  function docEmit(d, ch, nodeIdx, off) {
    if (WS.test(ch)) {
      if (d.chars.length) d.pendingSpace = true;
      return;
    }
    if (d.pendingSpace) {
      d.chars.push(' ');
      d.mn.push(nodeIdx);
      d.mo.push(off);
      d.pendingSpace = false;
    }
    d.chars.push(ch);
    d.mn.push(nodeIdx);
    d.mo.push(off);
  }

  // Закрыть текущий блок и открыть следующий с этого места.
  function docBreak(d, heading) {
    const at = d.chars.length;
    if (at > d.blockStart) d.blocks.push({ s: d.blockStart, e: at, heading: d.blockHead });
    d.blockStart = at;
    d.blockHead = !!heading;
    if (at) d.pendingSpace = true;   // «…конец.» и «Дальше…» не склеиваются
  }

  function docFinish(d) {
    docBreak(d, false);
    if (!d.chars.length) return null;
    d.text = d.chars.join('');
    d.mapNode = Int32Array.from(d.mn);
    d.mapOff = Int32Array.from(d.mo);
    d.chars = d.mn = d.mo = null;
    return d;
  }

  // Ближайший блочный предок. По имени тега, а не через getComputedStyle:
  // на главе в тысячу узлов второе стоит заметных миллисекунд, а ошибается
  // редкая вёрстка.
  function nearestBlock(node, root) {
    let el = node.parentNode;
    while (el && el !== root && el.nodeType === Node.ELEMENT_NODE) {
      if (BLOCK_TAGS.has(el.nodeName)) return el;
      el = el.parentNode;
    }
    return root;
  }

  // Одна и та же прогулка на оба случая. opts: {range, page, skip}.
  function collectInto(d, root, opts) {
    const o = opts || {};
    const range = o.range || null;
    const startText = range && range.startContainer.nodeType === Node.TEXT_NODE ? range.startContainer : null;
    const endText = range && range.endContainer.nodeType === Node.TEXT_NODE ? range.endContainer : null;

    const walker = document.createTreeWalker(
      root,
      NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT,
      {
        acceptNode(node) {
          if (node.nodeType === Node.ELEMENT_NODE) {
            if (node === o.skip || isOurPanel(node)) return NodeFilter.FILTER_REJECT;
            const tag = node.nodeName.toUpperCase();   // у SVG имена тегов строчные
            if (HARD_SKIP.has(tag)) return NodeFilter.FILTER_REJECT;
            if (o.page) {
              if (PAGE_SKIP.has(tag)) return NodeFilter.FILTER_REJECT;
              if (isJunkEl(node)) return NodeFilter.FILTER_REJECT;
              if (o.m && isNavBlock(node, o.m)) return NodeFilter.FILTER_REJECT;
              if (isHiddenEl(node)) return NodeFilter.FILTER_REJECT;
            }
          }
          if (range) {
            try {
              if (!range.intersectsNode(node)) return NodeFilter.FILTER_REJECT;
            } catch (e) { /* чужая реализация может не уметь — берём узел */ }
          }
          return NodeFilter.FILTER_ACCEPT;
        },
      }
    );

    let node;
    while ((node = walker.nextNode())) {
      if (node.nodeType === Node.ELEMENT_NODE) {
        // <br> — тоже граница блока: на сайтах с ранобэ абзацы разделены
        // именно им, а не <p>.
        if (node.nodeName === 'BR') d.forceBlock = true;
        continue;
      }
      const value = node.nodeValue || '';
      let from = 0;
      let to = value.length;
      if (node === startText) from = range.startOffset;
      if (node === endText) to = range.endOffset;
      if (from >= to) continue;
      // Пробельный узел не регистрируем, но пробел от него сохраняем: иначе
      // «<span>слово</span> <span>другое</span>» слипнется в «словодругое».
      if (!NONSPACE.test(from || to !== value.length ? value.slice(from, to) : value)) {
        if (d.chars.length) d.pendingSpace = true;
        continue;
      }
      const blk = nearestBlock(node, root);
      if (d.forceBlock || blk !== d.blockEl) {
        docBreak(d, blk && blk.nodeType === Node.ELEMENT_NODE && HEADING_TAGS.has(blk.nodeName));
        d.blockEl = blk;
        d.forceBlock = false;
      }
      const idx = d.nodes.push(node) - 1;
      for (let k = from; k < to; k++) docEmit(d, value[k], idx, k);
    }
    return d;
  }

  // Живой DOM между построением якорей и подсветкой мог перерисоваться:
  // дочитался комментарий, приехала ленивая картинка, React обновил ветку.
  // Отвалившийся Range не восстанавливаем (цена высокая, случай редкий) —
  // чанк читается, просто без подсветки.
  function rangeForSpan(doc, s, e) {
    if (!doc || e <= s || !doc.mapNode || e > doc.mapNode.length) return null;
    const a = doc.nodes[doc.mapNode[s]];
    const b = doc.nodes[doc.mapNode[e - 1]];
    if (!a || !b || !a.isConnected || !b.isConnected) return null;
    try {
      const r = document.createRange();
      r.setStart(a, doc.mapOff[s]);
      r.setEnd(b, doc.mapOff[e - 1] + 1);
      return r;
    } catch (err) {
      return null;
    }
  }

  // --- 3.2 фильтр узлов ---

  function isJunkEl(el) {
    const cls = typeof el.className === 'string' ? el.className : '';
    const id = el.id || '';
    if (!cls && !id) return false;
    return JUNK_RE.test(cls + ' ' + id);
  }

  // Меню, у которого нет ни говорящего тега, ни говорящего класса: блок, где
  // три четверти текста — ссылки. Считается по той же мерке, что и контейнер,
  // поэтому лишнего прохода по дереву не стоит.
  function isNavBlock(el, m) {
    return m.nav.has(el);
  }

  function isHiddenEl(el) {
    if (el.hidden) return true;
    if (el.getAttribute && el.getAttribute('aria-hidden') === 'true') return true;
    // Дешёвая проверка отправляет к дорогой, но не решает сама: offsetParent
    // пуст не только у display:none, но и у position:fixed, и у самого body.
    // А visibility:hidden она не ловит вовсе — там бокс есть.
    let st;
    try { st = getComputedStyle(el); } catch (e) { return false; }
    if (!st) return false;
    if (st.display === 'none' || st.visibility === 'hidden' || st.visibility === 'collapse') return true;
    return false;
  }

  // --- 3.3 поиск контейнера статьи ---
  //
  // Свой скоринг прямо по живому DOM вместо Readability: тот работает на клоне
  // документа и отдаёт текст, оторванный от страницы, — подсвечивать в нём
  // нечего. Здесь у каждого найденного куска сразу есть живой узел.

  function collapsedLen(s) {
    return s.replace(/\s+/g, ' ').trim().length;
  }

  // Длина текста, ссылочного текста и число потомков — снизу вверх за один
  // проход. getElementsByTagName отдаёт узлы в порядке документа, значит
  // обход с конца гарантирует, что дети посчитаны раньше родителей.
  function measureTree(root) {
    const all = root.getElementsByTagName('*');
    const text = new Map();
    const link = new Map();
    const desc = new Map();
    const nav = new Set();
    for (let i = all.length - 1; i >= 0; i--) {
      const el = all[i];
      let t = 0;
      let l = 0;
      let d = 0;
      for (let c = el.firstChild; c; c = c.nextSibling) {
        if (c.nodeType === Node.TEXT_NODE) t += collapsedLen(c.nodeValue || '');
        else if (c.nodeType === Node.ELEMENT_NODE) {
          t += text.get(c) || 0;
          l += link.get(c) || 0;
          d += (desc.get(c) || 0) + 1;
        }
      }
      const tag = el.nodeName.toUpperCase();
      // То, что читать всё равно не будем, и весить не должно: иначе меню и
      // подвал раздувают оценку своего родителя.
      if (HARD_SKIP.has(tag) || PAGE_SKIP.has(tag) || isJunkEl(el)) { t = 0; l = 0; }
      else if (tag === 'A') l = t;
      // Блок-обёртка, которая на три четверти состоит из ссылок, — это меню,
      // даже если ни тег, ни класс об этом не сказали. Абзац и пункт списка по
      // этому правилу не судим: в статье бывает абзац сплошь из ссылок (на
      // Википедии такой нашёлся), а меню всё равно попадётся выше, на <ul> или
      // <div>, потому что их собственная плотность считается по сумме детей.
      else if (CONTAINER_TAGS.has(tag) && t >= 20 && l / t >= NAV_LINK_DENSITY) {
        t = 0;
        l = 0;
        nav.add(el);
      }
      text.set(el, t);
      link.set(el, l);
      desc.set(el, d);
    }
    return { text, link, desc, nav };
  }

  function candidateOk(el, m) {
    if (!el || !el.isConnected) return false;
    if (isJunkEl(el) || isHiddenEl(el)) return false;
    const t = m.text.get(el) || 0;
    const l = m.link.get(el) || 0;
    if (t - l < MIN_CONTAINER_TEXT) return false;
    return l / Math.max(t, 1) <= MAX_LINK_DENSITY;
  }

  // Ядро идеи Readability в одну формулу: чистый текст, делённый на разметку.
  // Делим на корень из числа потомков, а не на само число, как говорило ТЗ:
  // при линейном делении одинокий длинный <p> (500 знаков, нуль потомков)
  // обгоняет свой же контейнер с двадцатью абзацами, и читаться будет один
  // абзац. Корень сохраняет смысл штрафа за разметку, но контейнер всё-таки
  // выигрывает.
  function scoreOf(el, m) {
    const t = m.text.get(el) || 0;
    const l = m.link.get(el) || 0;
    return (t - l) / Math.sqrt((m.desc.get(el) || 0) + 1);
  }

  function ownText(el, m) {
    return (m.text.get(el) || 0) - (m.link.get(el) || 0);
  }

  // Сужаем, пока ничего не теряем: берём самый маленький узел, в котором
  // остаётся почти весь текст найденного. Явная разметка часто шире статьи —
  // на Википедии <main> вмещает и «Материал из Википедии», и плашку о защите,
  // на новостном сайте — рубрику, дату и меню разделов. Заголовок при этом
  // теряться не боится: его подбирает findTitle отдельно.
  function narrow(el, m) {
    const need = ownText(el, m) * NARROW_KEEP;
    if (need < MIN_CONTAINER_TEXT) return el;
    let best = el;
    const all = el.getElementsByTagName('*');
    for (let i = 0; i < all.length; i++) {
      const c = all[i];
      if (!CONTAINER_TAGS.has(c.nodeName)) continue;
      if (ownText(c, m) < need) continue;
      if ((m.desc.get(c) || 0) < (m.desc.get(best) || 0)) best = c;
    }
    return best;
  }

  function findContainer() {
    const body = document.body;
    if (!body) return document.documentElement;
    const m = measureTree(body);

    const cands = [];
    for (const sel of CONTAINER_SELECTORS.concat(CONTAINER_HINTS)) {
      let list;
      try { list = document.querySelectorAll(sel); } catch (e) { continue; }
      for (const el of list) if (candidateOk(el, m) && cands.indexOf(el) < 0) cands.push(el);
    }
    let picked = null;
    for (const el of cands) {
      if (!picked || ownText(el, m) > ownText(picked, m)) picked = el;
    }
    if (!picked) {
      let bestScore = 0;
      const all = body.getElementsByTagName('*');
      for (let i = 0; i < all.length; i++) {
        const el = all[i];
        if (!CONTAINER_TAGS.has(el.nodeName)) continue;
        if (!candidateOk(el, m)) continue;
        const s = scoreOf(el, m);
        if (s > bestScore) { bestScore = s; picked = el; }
      }
    }
    return { el: narrow(picked || body, m), m };
  }

  // Контейнер запоминаем на страницу: повторное нажатие не пересчитывает.
  // Заодно переживает мерка дерева — фильтр меню считает по ней же.
  let cachedContainer = null;

  function articleContainer() {
    if (cachedContainer && cachedContainer.el && cachedContainer.el.isConnected) return cachedContainer;
    cachedContainer = findContainer();
    return cachedContainer;
  }

  // Заголовок статьи читается первым. Ищем внутри контейнера, а если его там
  // нет — над ним: на Википедии h1 живёт выше блока с текстом.
  function findTitle(container) {
    let h = container.querySelector('h1');
    if (!h) {
      const all = document.querySelectorAll('h1');
      for (const el of all) {
        if (container.contains(el)) continue;
        if (el.contains(container) || !el.isConnected) continue;
        h = el;
        break;
      }
    }
    if (!h || isHiddenEl(h) || isJunkEl(h)) return null;
    const t = collapsedLen(h.textContent || '');
    return t >= 2 && t <= 300 ? h : null;
  }

  // --- 3.4 сборка ---

  function buildFromRange(range) {
    const cac = range.commonAncestorContainer;
    const root = cac.nodeType === Node.TEXT_NODE ? cac.parentNode : cac;
    if (!root) return null;
    return docFinish(collectInto(newDoc(), root, { range }));
  }

  function buildFromPage(found) {
    const container = found.el;
    const m = found.m;
    const d = newDoc();
    const title = findTitle(container);
    if (title) {
      collectInto(d, title, { page: true, m });
      d.forceBlock = true;   // между заголовком и первым абзацем — своя граница
    }
    collectInto(d, container, { page: true, m, skip: title });
    return docFinish(d);
  }

  function firstTextIn(node) {
    if (!node) return null;
    if (node.nodeType === Node.TEXT_NODE) return node;
    if (node.nodeType !== Node.ELEMENT_NODE) return null;
    const w = document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
    return w.nextNode();
  }

  // Каретка после клика: читаем с абзаца, в котором она стоит, и до конца
  // статьи. Возвращаться к заголовку, когда человек дочитал до середины
  // главы, — ровно то, что бесит в чужих читалках.
  function caretOffset(doc) {
    const sel = window.getSelection();
    if (!sel || !sel.rangeCount || !sel.isCollapsed) return -1;
    const r = sel.getRangeAt(0);
    let node = r.startContainer;
    let off = r.startOffset;
    if (node.nodeType !== Node.TEXT_NODE) {
      node = firstTextIn(node.childNodes[off] || node.lastChild || node);
      off = 0;
      if (!node) return -1;
    }
    const ni = doc.nodes.indexOf(node);
    if (ni < 0) return -1;
    const mapNode = doc.mapNode;
    const mapOff = doc.mapOff;
    for (let k = 0; k < mapNode.length; k++) {
      if (mapNode[k] < ni) continue;
      if (mapNode[k] > ni) return k;
      if (mapOff[k] >= off) return k;
    }
    return -1;
  }

  // Смещение начала блока, в который попала каретка.
  function blockStartAt(doc, off) {
    if (off < 0) return 0;
    for (const b of doc.blocks) {
      if (off < b.e) return b.s;
    }
    return 0;
  }

  // ==== 4. Резка на чанки ================================================

  function startsSentence(ch) {
    if (!ch) return false;
    if (UPPER.test(ch)) return true;
    if (ch >= '0' && ch <= '9') return true;
    return '—–-«"\'“‘(['.indexOf(ch) !== -1;
  }

  // Точка после сокращения или инициала предложение не заканчивает.
  function isAbbrevOrInitial(text, dotIdx) {
    if (text[dotIdx] !== '.') return false;
    let s = dotIdx;
    while (s > 0 && LETTER_OR_DOT.test(text[s - 1])) s--;
    const token = text.slice(s, dotIdx + 1).toLowerCase();
    if (ABBREV.has(token)) return true;
    // Инициал — одна заглавная, и обязательно отдельным словом: иначе
    // «нажал Ctrl+S. Потом…» тоже сойдёт за инициал и предложение не порежется.
    const bare = text.slice(s, dotIdx);
    if (bare.length !== 1 || !UPPER.test(bare)) return false;
    return s === 0 || WS.test(text[s - 1]) || '«"\'“‘(—–-'.indexOf(text[s - 1]) !== -1;
  }

  function isTerminalAbbrev(text, dotIdx) {
    if (text[dotIdx] !== '.') return false;
    let s = dotIdx;
    while (s > 0 && LETTER_OR_DOT.test(text[s - 1])) s--;
    return ABBREV_TERMINAL.has(text.slice(s, dotIdx + 1).toLowerCase());
  }

  function splitSentences(text, from, to) {
    const spans = [];
    const n = to === undefined ? text.length : to;
    let start = from || 0;
    let i = start;
    while (i < n) {
      if (TERMINATORS.indexOf(text[i]) === -1) { i++; continue; }
      let j = i;
      while (j < n && TERMINATORS.indexOf(text[j]) !== -1) j++;   // «...», «?!»
      while (j < n && CLOSERS.indexOf(text[j]) !== -1) j++;       // «…конец.» Дальше
      if (j < n && !WS.test(text[j])) { i = j; continue; }
      const blocked = isAbbrevOrInitial(text, j - 1) || isAbbrevOrInitial(text, i);
      if (!blocked || isTerminalAbbrev(text, i)) {
        let k = j;
        while (k < n && WS.test(text[k])) k++;
        // Следующее предложение начинается с заглавной, тире или кавычки.
        // «— Я… не знаю.» на этой проверке и не режется: после многоточия
        // строчная «не».
        if (k >= n || startsSentence(text[k])) {
          if (j > start) spans.push([start, j]);
          start = k;
          i = k;
          continue;
        }
      }
      i = j;
    }
    if (start < n) spans.push([start, n]);
    return spans;
  }

  function trimSpan(text, span) {
    let [s, e] = span;
    while (e > s && WS.test(text[e - 1])) e--;
    while (s < e && WS.test(text[s])) s++;
    return [s, e];
  }

  function mergeShort(text, spans) {
    const out = [];
    for (const span of spans) {
      const prev = out[out.length - 1];
      if (prev && (prev[1] - prev[0]) < MERGE_SHORT && (span[1] - prev[0]) <= MAX_CHUNK) {
        prev[1] = span[1];
      } else {
        out.push([span[0], span[1]]);
      }
    }
    return out;
  }

  // Длинное предложение режем по запятым, двоеточиям и тире. Интонация
  // просядет — Silero доводит каждый кусок до законченной фразы, — но это
  // меньшее зло, чем десятисекундное ожидание одного куска.
  function splitLong(text, span, maxLen, minLen) {
    const out = [];
    let [s, e] = span;
    while (e - s > maxLen) {
      const hi = Math.min(s + maxLen, e - 1);
      const lo = Math.min(s + minLen, hi);
      let cut = -1;
      for (let p = lo; p <= hi; p++) {
        if (SOFT_BREAKS.indexOf(text[p]) !== -1 && (p + 1 >= e || WS.test(text[p + 1]))) cut = p + 1;
      }
      if (cut === -1) {
        for (let p = lo; p <= hi; p++) if (WS.test(text[p])) cut = p;
      }
      if (cut === -1 || cut <= s) cut = hi + 1;
      out.push([s, cut]);
      let ns = cut;
      while (ns < e && WS.test(text[ns])) ns++;
      s = ns;
    }
    if (s < e) out.push([s, e]);
    return out;
  }

  // Первый чанк — по ПЕРВОМУ подходящему знаку, не по последнему: важна
  // не ровность кусков, а то, через сколько миллисекунд начнётся звук.
  function cutFirst(text, span) {
    const [s, e] = span;
    if (e - s <= FIRST_CHUNK_MAX) return [span];
    const hi = Math.min(s + FIRST_CHUNK_MAX, e - 1);
    const lo = Math.min(s + FIRST_CHUNK_MIN, hi);
    let cut = -1;
    for (let p = lo; p <= hi; p++) {
      if (SOFT_BREAKS.indexOf(text[p]) !== -1 && (p + 1 >= e || WS.test(text[p + 1]))) { cut = p + 1; break; }
    }
    if (cut === -1) {
      for (let p = hi; p > lo; p--) if (WS.test(text[p])) { cut = p; break; }
    }
    if (cut === -1 || cut <= s) cut = hi + 1;
    let ns = cut;
    while (ns < e && WS.test(text[ns])) ns++;
    if (ns >= e) return [span];
    return [[s, cut], [ns, e]];
  }

  // Во сколько знаков превратится чанк после нормализации на сервере.
  function budget(text, s, e) {
    let n = e - s;
    for (let p = s; p < e; p++) {
      const c = text[p];
      if (c >= '0' && c <= '9') n += DIGIT_COST;
      else if (LATIN.test(c)) n += LATIN_COST;
    }
    return n;
  }

  function fitBudget(text, span, out) {
    const [s, e] = span;
    if (e - s <= MERGE_SHORT || budget(text, s, e) <= BUDGET_LIMIT) { out.push(span); return; }
    let mid = Math.floor((s + e) / 2);
    let probe = mid;
    while (probe > s + 10 && !WS.test(text[probe])) probe--;
    if (probe > s + 10) mid = probe;
    fitBudget(text, [s, mid], out);
    let ns = mid;
    while (ns < e && WS.test(text[ns])) ns++;
    if (ns < e) fitBudget(text, [ns, e], out);
  }

  function chunkSegment(text, from, to, first) {
    let spans = splitSentences(text, from, to).map((sp) => trimSpan(text, sp)).filter((sp) => sp[1] > sp[0]);
    spans = mergeShort(text, spans);
    if (first && spans.length) spans = cutFirst(text, spans[0]).concat(spans.slice(1));

    const sized = [];
    spans.forEach((span, idx) => {
      const limit = (first && idx === 0) ? FIRST_CHUNK_MAX : MAX_CHUNK;
      for (const piece of splitLong(text, span, limit, Math.min(MIN_PIECE, limit - 20))) {
        fitBudget(text, piece, sized);
      }
    });

    return sized
      .map((sp) => trimSpan(text, sp))
      .filter((sp) => sp[1] > sp[0] && /[\p{L}\p{N}]/u.test(text.slice(sp[0], sp[1])));
  }

  // Блоки (абзацы) режутся порознь — чанк не перепрыгивает из абзаца в абзац.
  // Крошечные блоки при этом клеятся друг к другу: страница диалога, где каждая
  // реплика — свой <p>, иначе забьёт очередь односекундными запросами. Клеим
  // только коротыш к коротышу: приклеить целый абзац к реплике — значит и паузу
  // между ними потерять, и подсветить разом полстраницы. Заголовок не клеим
  // никогда: пауза после него и есть смысл затеи.
  function segments(text, blocks) {
    if (!blocks || !blocks.length) return [{ s: 0, e: text.length, heading: false }];
    const out = [];
    for (const b of blocks) {
      const [s, e] = trimSpan(text, [b.s, b.e]);
      if (e <= s) continue;
      const prev = out[out.length - 1];
      if (prev && !prev.heading && !b.heading &&
          (prev.e - prev.s) < MERGE_SHORT && (e - s) < MERGE_SHORT &&
          (e - prev.s) <= MAX_CHUNK) {
        prev.e = e;
        continue;
      }
      out.push({ s, e, heading: !!b.heading });
    }
    return out;
  }

  // Возвращает [начало, конец, пауза после чанка в мс].
  function chunkText(text, blocks) {
    const segs = segments(text, blocks);
    const out = [];
    for (const seg of segs) {
      const spans = chunkSegment(text, seg.s, seg.e, out.length === 0);
      if (!spans.length) continue;
      for (const sp of spans) out.push([sp[0], sp[1], 0]);
      out[out.length - 1][2] = seg.heading ? PAUSE_HEADING : PAUSE_BLOCK;
    }
    if (out.length) out[out.length - 1][2] = 0;   // в конце пауза ни к чему
    return out;
  }

  // ==== 5. Подсветка чанка и слова =======================================
  //
  // CSS Custom Highlight API: не трогает DOM, не ломает React-страницы.
  // Только background-color — text-decoration и text-shadow в ::highlight()
  // у Firefox не работают. Нет поддержки — работаем молча без подсветки,
  // в <span> не заворачиваем ни при каких условиях.
  //
  // Хайлайтов два: чанк (TTS-6, всегда) и слово внутри него (TTS-7A,
  // отключаемое). Слово перебивает чанк через priority — заливка рисуется
  // поверх, поэтому цвет слова взят того же тона, но насыщеннее: на глаз
  // это «то же место, только ярче», а не второй независимый цвет.

  const highlightSupported = typeof CSS !== 'undefined' && CSS.highlights && typeof Highlight === 'function';
  let highlightStyle = null;
  let highlightRange = null;
  let wordRange = null;

  function parseRgb(value) {
    const m = /rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:[,/\s]+([\d.]+))?/i.exec(value || '');
    if (!m) return null;
    const alpha = m[4] === undefined ? 1 : parseFloat(m[4]);
    if (!alpha) return null;
    return [parseFloat(m[1]), parseFloat(m[2]), parseFloat(m[3])];
  }

  // prefers-color-scheme говорит о вкусах системы, а слепит нас фон страницы.
  // Поэтому сначала смотрим на реальный фон, и только если он прозрачный —
  // спрашиваем систему.
  function pageIsDark() {
    for (const el of [document.body, document.documentElement]) {
      if (!el) continue;
      const rgb = parseRgb(getComputedStyle(el).backgroundColor);
      if (rgb) return (0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]) < 128;
    }
    return !!(window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
  }

  function ensureHighlightStyle() {
    if (!highlightSupported) return;
    const dark = pageIsDark();
    const color = GM_getValue('chunkColor', '') || (dark ? 'rgba(120, 170, 255, 0.32)' : 'rgba(255, 214, 0, 0.38)');
    const word = GM_getValue('wordColor', '') || (dark ? 'rgba(90, 140, 255, 0.62)' : 'rgba(255, 138, 0, 0.55)');
    const css = `::highlight(${HIGHLIGHT_NAME}) { background-color: ${color}; }\n`
      + `::highlight(${WORD_HIGHLIGHT_NAME}) { background-color: ${word}; }`;
    if (!highlightStyle || !highlightStyle.isConnected) {
      highlightStyle = document.createElement('style');
      (document.head || document.documentElement).appendChild(highlightStyle);
    }
    highlightStyle.textContent = css;
  }

  // range === null — это не «оставить как было», а «подсвечивать нечего»:
  // якорь отвалился вместе с перерисованным куском страницы (§6 ТЗ).
  function showHighlight(range) {
    if (!range) { clearHighlight(); return; }
    if (GM_getValue('highlightChunk', true) === false) { clearChunkHighlight(); return; }
    if (!highlightSupported) return;
    ensureHighlightStyle();
    try {
      CSS.highlights.set(HIGHLIGHT_NAME, new Highlight(range));
      highlightRange = range;
    } catch (e) { /* чужая страница могла сломать Range — не беда */ }
  }

  function clearChunkHighlight() {
    highlightRange = null;
    if (!highlightSupported) return;
    try { CSS.highlights.delete(HIGHLIGHT_NAME); } catch (e) { /* ignore */ }
  }

  function clearHighlight() {
    clearChunkHighlight();
    clearWordHighlight();
  }

  // priority выставляется на самом объекте Highlight, а не в CSS: при
  // равном приоритете порядок отрисовки задаётся порядком регистрации, и
  // слово, зарегистрированное раньше чанка (после перезаписи чанка оно
  // может оказаться и таким), ушло бы под него.
  function showWordHighlight(range) {
    if (!range) { clearWordHighlight(); return; }
    if (!highlightSupported) return;
    ensureHighlightStyle();
    try {
      const h = new Highlight(range);
      h.priority = 1;
      CSS.highlights.set(WORD_HIGHLIGHT_NAME, h);
      wordRange = range;
    } catch (e) { /* чужая страница могла сломать Range — не беда */ }
  }

  function clearWordHighlight() {
    wordRange = null;
    if (!highlightSupported) return;
    try { CSS.highlights.delete(WORD_HIGHLIGHT_NAME); } catch (e) { /* ignore */ }
  }

  // ==== 6. Прокрутка вслед за чтением ====================================

  let ourScrollAt = -Infinity;

  function followScroll() {
    if (!P.follow || !GM_getValue('followScroll', true)) return;
    const chunk = P.chunks[P.index];
    const range = highlightRange || (P.doc && chunk && rangeForSpan(P.doc, chunk.s, chunk.e));
    if (!range) return;
    let rect;
    try { rect = range.getBoundingClientRect(); } catch (e) { return; }
    if (!rect || (!rect.width && !rect.height)) return;
    const vh = window.innerHeight || document.documentElement.clientHeight;
    if (rect.top >= 0 && rect.bottom <= vh) return;   // и так видно
    ourScrollAt = performance.now();
    try {
      window.scrollTo({ top: window.scrollY + rect.top - vh / 2, behavior: 'smooth' });
    } catch (e) {
      window.scrollTo(0, window.scrollY + rect.top - vh / 2);
    }
  }

  // Своя плавная прокрутка сыплет событиями ещё секунду после вызова, поэтому
  // «прокрутил человек» = событие, пришедшее не в окне после нашего вызова.
  window.addEventListener('scroll', () => {
    if (P.state === 'idle' || P.state === 'ended') return;
    if (performance.now() - ourScrollAt < OWN_SCROLL_WINDOW) return;
    P.follow = false;   // до конца чтения больше не догоняем
  }, { passive: true, capture: true });

  // ==== 7. Панель ========================================================
  //
  const panel = { host: null, root: null, els: null, hideTimer: null, settings: false, capturing: false,
    dictRevision: 0, dictDirty: false };

  function panelPosition() {
    if (!panel.host) return;
    const corner = GM_getValue('panelCorner', 'bottom-right');
    const x = Math.max(0, Math.min(1000, Number(GM_getValue('panelX', 16)) || 0));
    const y = Math.max(0, Math.min(1000, Number(GM_getValue('panelY', 16)) || 0));
    const s = panel.host.style;
    s.setProperty('left', corner.endsWith('left') ? `${x}px` : 'auto', 'important');
    s.setProperty('right', corner.endsWith('right') ? `${x}px` : 'auto', 'important');
    s.setProperty('top', corner.startsWith('top') ? `${y}px` : 'auto', 'important');
    s.setProperty('bottom', corner.startsWith('bottom') ? `${y}px` : 'auto', 'important');
    panel.root.querySelector('.panel-layout').classList.toggle('bottom', corner.startsWith('bottom'));
  }

  function buildPanel() {
    if (panel.host) return;
    const host = document.createElement('div');
    host.id = 'skaz-panel-host';
    host.tabIndex = 0;
    Object.assign(host.style, {
      position: 'fixed', zIndex: 2147483000, width: 'auto', height: 'auto',
      margin: '0', padding: '0', border: '0', display: 'none',
    });
    for (const [name, value] of Object.entries({
      all: 'initial', position: 'fixed', 'z-index': '2147483000', display: 'none',
    })) host.style.setProperty(name, value, 'important');
    const root = host.attachShadow({ mode: 'closed' });
    root.innerHTML = `
      <style>
        :host { all: initial; color-scheme: dark; }
        [hidden] { display:none !important; }
        .panel-layout { display:flex; flex-direction:column; align-items:center; gap:8px; }
        .panel-layout.bottom { flex-direction:column-reverse; }
        .box {
          box-sizing:border-box; max-width:calc(100vw - 32px);
          display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
          font: 13px/1.3 system-ui, -apple-system, "Segoe UI", sans-serif;
          background: #1f2023; color: #f0f0f0;
          padding: 8px 10px; border-radius: 8px;
          box-shadow: 0 4px 16px rgba(0,0,0,0.35);
          user-select: none;
        }
        button, input, select, textarea { box-sizing: border-box; font: inherit; }
        button {
          font: inherit; color: inherit; background: #33353a; border: 0;
          border-radius: 5px; padding: 4px 9px; cursor: pointer; min-width: 28px;
        }
        button:hover { background: #45484f; }
        button:disabled { opacity: 0.4; cursor: default; }
        .pos { min-width: 62px; text-align: center; font-variant-numeric: tabular-nums; }
        .rate { min-width: 34px; text-align: center; font-variant-numeric: tabular-nums; }
        .note { max-width: 260px; color: #ffca6a; }
        .compatibility { color:#ffca6a; }
        .note:empty { display: none; }
        .install { color: #9fc1ff; }
        .sep { width: 1px; align-self: stretch; background: #45484f; }
        .spinner { display:none; color:#ffca6a; }
        .spinner.on { display:inline; }
        .settings { box-sizing:border-box; display:none; width:min(448px, calc(100vw - 32px)); max-height:75vh; overflow:auto;
          padding:14px; background:#1f2023; color:#f0f0f0; border-radius:8px;
          box-shadow:0 4px 16px #0006; font:13px/1.4 system-ui,sans-serif; }
        .settings.open { display:block; }
        .settings h2 { font-size:17px; margin:0 0 8px; }
        .settings label { display:flex; align-items:center; justify-content:space-between; gap:12px; margin:8px 0; }
        .settings input:not([type=checkbox]),.settings select,.settings textarea {
          width:180px; max-width:55%; padding:5px; border:1px solid #747b87; border-radius:4px;
          color:#fff; background:#30333a; }
        .settings input[type=color] { padding:0; width:52px; height:28px; }
        .settings textarea { width:100%; max-width:none; min-height:90px; font:12px/1.4 Consolas,monospace; }
        .dictRows { display:grid; gap:5px; margin:8px 0; }
        .dictRow { display:flex; gap:5px; }
        .dictRow input { flex:1; min-width:0; max-width:none !important; }
        .settings .actions { display:flex; flex-wrap:wrap; gap:4px; margin:8px 0; }
        .settings .message { min-height:20px; color:#ffca6a; overflow-wrap:anywhere; }
        .settings a { color:#9fc1ff; }
        .settings hr { border:0; border-top:1px solid #555; margin:12px 0; }
        .updatePrompt { display:none; box-sizing:border-box; width:min(380px, calc(100vw - 32px)); padding:14px;
          background:#1f2023; color:#f0f0f0; border:1px solid #ffca6a; border-radius:8px;
          box-shadow:0 4px 16px #0006; font:13px/1.4 system-ui,sans-serif; }
        .updatePrompt.open { display:block; }
        .updatePrompt strong { display:block; margin-bottom:7px; }
        .updatePrompt .actions { display:flex; gap:8px; margin-top:10px; }
      </style>
      <div class="panel-layout">
      <div class="box" part="box">
        <button class="play" title="Пауза / продолжить (хоткей или пробел)">⏸</button>
        <button class="prev" title="Предыдущее предложение (Alt+←)">‹</button>
        <button class="next" title="Следующее предложение (Alt+→)">›</button>
        <span class="pos">— / —</span>
        <span class="spinner" title="Буферизация">◌</span>
        <span class="sep"></span>
        <button class="slower" title="Медленнее (Alt+↓)">−</button>
        <span class="rate">1.0×</span>
        <button class="faster" title="Быстрее (Alt+↑)">+</button>
        <span class="sep"></span>
        <button class="stop" title="Стоп (Escape)">✕</button>
        <button class="gear" title="Настройки">⚙</button>
        <span class="note"></span>
        <a class="compatibility" href="https://github.com/Qwill552/SKAZ/releases/latest" target="_blank" rel="noopener noreferrer" hidden></a>
        <button class="startServer" type="button" hidden>Запустить</button>
        <a class="install" target="_blank" rel="noopener noreferrer" hidden>Установка</a>
      </div>
      <section class="updatePrompt" role="dialog" aria-label="Обновление SKAZ">
        <strong class="updateTitle"></strong>
        <div class="updateDetails"></div>
        <div class="actions"><button class="applyUpdate" type="button">Обновить</button><button class="laterUpdate" type="button">Позже</button></div>
      </section>
      <section class="settings" aria-label="Настройки SKAZ">
        <h2>Настройки SKAZ</h2>
        <label>Голос <select class="voice"></select></label>
        <label>Скорость по умолчанию <input class="defaultRate" type="number" min="0.5" max="2.5" step="0.1"></label>
        <label>Горячая клавиша <button class="hotkey" type="button"></button></label>
        <label>Подсветка предложения <input class="highlightChunk" type="checkbox"></label>
        <label>Цвет предложения <input class="chunkColor" type="color"></label>
        <label>Подсветка слова <input class="highlightWords" type="checkbox"></label>
        <label>Цвет слова <input class="wordColor" type="color"></label>
        <label>Догонять прокруткой <input class="followScroll" type="checkbox"></label>
        <label>Префетч <select class="prefetch"><option>1</option><option>2</option><option>3</option><option>4</option></select></label>
        <hr>
        <label>Угол <select class="panelCorner"><option value="bottom-right">Справа снизу</option><option value="bottom-left">Слева снизу</option><option value="top-right">Справа сверху</option><option value="top-left">Слева сверху</option></select></label>
        <label>Смещение по X, px <input class="panelX" type="number" min="0" max="1000"></label>
        <label>Смещение по Y, px <input class="panelY" type="number" min="0" max="1000"></label>
        <button class="resetPosition" type="button">Сбросить положение</button>
        <hr>
        <label>Адрес сервера <input class="baseUrl" type="url"></label>
        <label>Ключ <input class="token" type="password" autocomplete="off"></label>
        <div class="actions"><button class="saveServer">Сохранить</button><button class="checkServer">Проверить связь</button><button class="openSetup">Открыть /setup</button></div>
        <div class="health message"></div>
        <hr>
        <strong>Словарь замен</strong>
        <p>Пример: <code>Цунаде → Цун+адэ</code>. Слева — слово на странице, справа — как его произнести.</p>
        <p><code>+</code> перед гласной ставит ударение, <code>-</code> между словами добавляет паузу.
        Ударение в основе переносится на обычные падежные формы: <code>Фердинанд → Фердин+анд</code>
        работает и для «Фердинанда».</p>
        <div class="dictRows"></div>
        <input class="dictFile" type="file" accept=".json,application/json" hidden>
        <div class="actions"><button class="addDict">Добавить строку</button><button class="importDict">Импорт JSON</button><button class="saveDict">Сохранить словарь</button></div>
        <div class="dictMessage message"></div>
        <hr>
        <div>Версия скрипта: ${SCRIPT_VERSION}</div>
        <div>Репозиторий: <a href="https://github.com/Qwill552/SKAZ" target="_blank" rel="noopener noreferrer">Qwill552/SKAZ</a></div>
        <button class="checkUpdate">Проверить обновления</button>
        <div class="updateMessage message"></div>
      </section></div>`;
    (document.body || document.documentElement).appendChild(host);

    const q = (sel) => root.querySelector(sel);
    panel.host = host;
    panel.root = root;
    panelPosition();
    panel.els = {
      play: q('.play'), prev: q('.prev'), next: q('.next'),
      pos: q('.pos'), rate: q('.rate'), note: q('.note'),
      slower: q('.slower'), faster: q('.faster'), stop: q('.stop'),
      gear: q('.gear'), spinner: q('.spinner'), settings: q('.settings'),
      startServer: q('.startServer'), install: q('.install'),
      hotkey: q('.hotkey'), updatePrompt: q('.updatePrompt'), compatibility: q('.compatibility'),
    };

    panel.els.play.addEventListener('click', togglePause);
    panel.els.prev.addEventListener('click', () => jump(-1));
    panel.els.next.addEventListener('click', () => jump(1));
    panel.els.slower.addEventListener('click', () => nudgeRate(-RATE_STEP));
    panel.els.faster.addEventListener('click', () => nudgeRate(RATE_STEP));
    panel.els.stop.addEventListener('click', () => stopReading());
    panel.els.gear.addEventListener('click', () => panel.settings ? closeSettings() : openSettings());
    panel.els.startServer.addEventListener('click', launchServer);
    q('.applyUpdate').addEventListener('click', applyUpdate);
    q('.laterUpdate').addEventListener('click', closeUpdatePrompt);
    wireSettings(q);
    // Пробел при фокусе на панели = пауза. Слушаем на хосте: события из
    // теневого дерева всплывают сюда уже с ретаргетингом.
    host.addEventListener('keydown', (e) => {
      if (e.code === 'Space' && e.composedPath()[0] === host) {
        e.preventDefault(); e.stopPropagation(); togglePause();
      }
    });
  }

  function gmJson(method, url, data, token, timeout = 5000) {
    return new Promise((resolve, reject) => {
      GM_xmlhttpRequest({
        method, url, timeout, responseType: 'text',
        headers: {
          ...(data === undefined ? {} : { 'Content-Type': 'application/json' }),
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        ...(data === undefined ? {} : { data: JSON.stringify(data) }),
        onload: (r) => {
          let body = {};
          try { body = JSON.parse(r.responseText || r.response || '{}'); } catch (e) { /* leave empty */ }
          if (r.status >= 200 && r.status < 300) resolve(body);
          else reject(new Error(r.status === 401 ? 'Неверный ключ' : `Сервер ответил ${r.status}`));
        },
        onerror: () => reject(new Error('Сервер не отвечает')),
        ontimeout: () => reject(new Error('Сервер не отвечает')),
      });
    });
  }

  async function discoverServer(token) {
    for (let port = 8756; port <= 8760; port++) {
      const url = `http://127.0.0.1:${port}`;
      try {
        const health = await gmJson('GET', `${url}/health`, undefined, token);
        GM_setValue('baseUrl', url);
        if (panel.els) panel.root.querySelector('.baseUrl').value = url;
        return health;
      } catch (e) { /* этот порт пуст или ключ от другого сервера */ }
    }
    throw new Error('Сервер не отвечает на портах 8756–8760');
  }

  function setSettingsMessage(selector, text) {
    if (panel.root) panel.root.querySelector(selector).textContent = text;
  }

  async function checkServer() {
    const token = GM_getValue('token', '');
    if (!token) { setSettingsMessage('.health', 'Сначала вставьте ключ.'); return; }
    setSettingsMessage('.health', 'Проверяю связь…');
    try {
      let health;
      try { health = await gmJson('GET', `${baseUrl()}/health`, undefined, token); }
      catch (e) { health = await discoverServer(token); }
      const loaded = health.model_loaded ? 'модель загружена' : 'модель пока не загружена';
      setSettingsMessage('.health', `Сервер ${health.version}, ${health.backend}, ${loaded}` +
        (health.protocol_version && health.protocol_version !== 1 ? ' · несовместимый протокол' : ''));
      showCompatibility(health.version);
      const select = panel.root.querySelector('.voice');
      const chosen = voice();
      select.replaceChildren();
      for (const name of health.voices || []) {
        const option = document.createElement('option'); option.value = name; option.textContent = name;
        select.appendChild(option);
      }
      if ((health.voices || []).includes(chosen)) select.value = chosen;
      loadDict();
    } catch (e) { setSettingsMessage('.health', e.message); }
  }

  function showCompatibility(serverVersion) {
    buildPanel();
    const scriptMajor = Number(SCRIPT_VERSION.split('.')[0]);
    const serverMajor = Number(String(serverVersion).split('.')[0]);
    const link = panel.els.compatibility;
    link.hidden = scriptMajor === serverMajor || !Number.isInteger(serverMajor);
    if (!link.hidden) {
      link.textContent = scriptMajor > serverMajor ? 'Скрипт новее сервера — обновите сервер' :
        'Сервер новее скрипта — обновите скрипт';
      showPanel();
    }
  }

  async function loadDict() {
    if (panel.dictDirty) return;
    const revision = panel.dictRevision;
    setSettingsMessage('.dictMessage', 'Загружаю словарь с сервера…');
    try {
      const data = await gmJson('GET', `${baseUrl()}/dict`, undefined, GM_getValue('token', ''));
      if (panel.dictRevision !== revision) return;
      renderDict(data.entries || {});
      setSettingsMessage('.dictMessage', `${Object.keys(data.entries || {}).length} записей`);
    } catch (e) { if (panel.dictRevision === revision) setSettingsMessage('.dictMessage', e.message); }
  }

  function dictEdited() {
    panel.dictRevision++;
    panel.dictDirty = true;
  }

  function renderDict(entries) {
    panel.root.querySelector('.dictRows').replaceChildren();
    for (const [key, value] of Object.entries(entries)) addDictRow(key, value);
  }

  function addDictRow(key = '', value = '') {
    const row = document.createElement('div'); row.className = 'dictRow';
    const from = document.createElement('input'); from.placeholder = 'Слово'; from.value = key;
    const to = document.createElement('input'); to.placeholder = 'Замена'; to.value = value;
    const del = document.createElement('button'); del.type = 'button'; del.textContent = '×'; del.title = 'Удалить';
    del.onclick = () => { row.remove(); dictEdited(); };
    from.oninput = to.oninput = dictEdited;
    row.append(from, to, del); panel.root.querySelector('.dictRows').appendChild(row);
    if (!key) from.focus();
  }

  function readDictRows() {
    const entries = Object.create(null);
    const seen = new Set();
    for (const row of panel.root.querySelectorAll('.dictRow')) {
      const [from, to] = row.querySelectorAll('input');
      const key = from.value.trim(), value = to.value.trim();
      if (!key && !value) continue;
      if (!key || !value) throw new Error('Заполните оба поля в строке словаря.');
      if (key.length > 120 || value.length > 240) throw new Error('Слово — до 120 знаков, замена — до 240.');
      if (seen.has(key.toLocaleLowerCase('ru'))) throw new Error(`Повторяется слово «${key}». Оставьте одну запись.`);
      seen.add(key.toLocaleLowerCase('ru'));
      entries[key] = value;
    }
    return entries;
  }

  function parseDictImport(text) {
    if (new TextEncoder().encode(text).length > 65536) throw new Error('Файл словаря должен быть не больше 64 КБ.');
    let data;
    try { data = JSON.parse(text.replace(/^\uFEFF/, '')); }
    catch (e) { throw new Error('Не удалось прочитать JSON. Выберите файл user_dict.json.'); }
    if (data && typeof data === 'object' && !Array.isArray(data) &&
        Object.keys(data).length === 1 && data.entries && typeof data.entries === 'object') data = data.entries;
    if (!data || typeof data !== 'object' || Array.isArray(data)) {
      throw new Error('Ожидается JSON вида {"Фердинанд":"Фердин+анд"}.');
    }
    const entries = Object.create(null);
    for (const [key, value] of Object.entries(data)) {
      if (!key.trim() || key.length > 120 || typeof value !== 'string' || !value.trim() || value.length > 240) {
        throw new Error('В каждой записи нужны слово и текст замены (до 120 и 240 знаков).');
      }
      entries[key.trim()] = value.trim();
    }
    return entries;
  }

  async function importDictFile(file) {
    if (!file) return;
    // Не дать опоздавшему GET /dict затереть импорт или ручные изменения.
    dictEdited();
    try {
      if (file.size > 65536) throw new Error('Файл словаря должен быть не больше 64 КБ.');
      const imported = parseDictImport(await file.text());
      const merged = new Map(Object.entries(readDictRows()).map(([key, value]) => [key.toLocaleLowerCase('ru'), [key, value]]));
      for (const [key, value] of Object.entries(imported)) merged.set(key.toLocaleLowerCase('ru'), [key, value]);
      const entries = Object.fromEntries(merged.values());
      if (new TextEncoder().encode(JSON.stringify(entries)).length > 65536) throw new Error('Общий словарь превышает 64 КБ.');
      renderDict(entries);
      setSettingsMessage('.dictMessage', `Импортировано ${Object.keys(imported).length} записей. Совпадающие слова обновлены. Нажмите «Сохранить словарь».`);
    } catch (e) { setSettingsMessage('.dictMessage', e.message); }
  }

  async function saveDict() {
    try {
      const entries = readDictRows();
      if (new TextEncoder().encode(JSON.stringify(entries)).length > 65536) throw new Error('Общий словарь превышает 64 КБ.');
      const revision = panel.dictRevision;
      await gmJson('PUT', `${baseUrl()}/dict`, entries, GM_getValue('token', ''));
      if (panel.dictRevision === revision) panel.dictDirty = false;
      setSettingsMessage('.dictMessage', panel.dictDirty ? 'Отправленные записи сохранены. Есть новые несохранённые правки.' :
        'Словарь сохранён. Следующее предложение прозвучит с заменами.');
      invalidateFutureAudio();
    } catch (e) { setSettingsMessage('.dictMessage', e.message); }
  }

  function newerVersion(tag, current) {
    const a = String(tag).replace(/^v/, '').split('.').map(Number);
    const b = String(current).replace(/^v/, '').split('.').map(Number);
    if (a.length !== 3 || b.length !== 3 || [...a, ...b].some(n => !Number.isInteger(n) || n < 0)) return false;
    for (let i = 0; i < 3; i++) { if ((a[i] || 0) !== (b[i] || 0)) return (a[i] || 0) > (b[i] || 0); }
    return false;
  }

  function closeUpdatePrompt() {
    if (!panel.els) return;
    panel.els.updatePrompt.classList.remove('open');
    panel.pendingUpdate = null;
    if (!panel.settings && !isActive()) hidePanel(0);
  }

  async function applyUpdate() {
    const pending = panel.pendingUpdate;
    if (!pending) return;
    panel.root.querySelector('.applyUpdate').disabled = true;
    if (pending.script) window.open(pending.scriptUrl, '_blank', 'noopener');
    try {
      if (pending.server) {
        const token = GM_getValue('token', '');
        if (!token) throw new Error('Сначала свяжите SKAZ с браузером.');
        await gmJson('POST', `${baseUrl()}/update`, {}, token, 10000);
      }
      panel.root.querySelector('.updateDetails').textContent = pending.server ?
        'Обновление запущено. Дождитесь перезапуска SKAZ.' : 'Подтвердите обновление в Tampermonkey.';
      GM_setValue('updatePromptedVersion', pending.version);
    } catch (e) {
      panel.root.querySelector('.updateDetails').textContent = `Не удалось запустить обновление: ${e.message}`;
    } finally {
      panel.root.querySelector('.applyUpdate').disabled = false;
    }
  }

  async function checkUpdates(automatic = false) {
    if (automatic && GM_getValue('releaseCheckStarted', 0) + 60000 > Date.now()) return;
    if (automatic) GM_setValue('releaseCheckStarted', Date.now());
    buildPanel();
    const box = panel.root.querySelector('.updateMessage');
    if (!automatic) box.textContent = 'Проверяю…';
    let release;
    try {
      release = await gmJson('GET', `https://api.github.com/repos/${GITHUB_REPO}/releases/latest`);
    } catch (e) {
      if (!automatic) box.textContent = `Не удалось проверить: ${e.message}`;
      return;
    }
    const version = String(release.tag_name || '').replace(/^v/, '');
    const script = newerVersion(version, SCRIPT_VERSION);
    let server = false;
    const token = GM_getValue('token', '');
    if (token) {
      try {
        const health = await gmJson('GET', `${baseUrl()}/health`, undefined, token, 1500);
        server = newerVersion(version, health.version);
        showCompatibility(health.version);
      } catch (e) { }
    }
    if (!script && !server) {
      if (!automatic) box.textContent = `Установлена актуальная версия (${SCRIPT_VERSION}).`;
      return;
    }
    if (!automatic) box.textContent = `Доступна версия ${version}.`;
    if (automatic && GM_getValue('updatePromptedVersion', '') === version) return;
    panel.pendingUpdate = { version, script, server,
      scriptUrl: `https://raw.githubusercontent.com/${GITHUB_REPO}/${encodeURIComponent(release.tag_name)}/userscript/skaz.user.js` };
    panel.root.querySelector('.updateTitle').textContent = `Доступна версия SKAZ ${version}`;
    panel.root.querySelector('.updateDetails').textContent =
      [server ? 'Обновится локальный сервер.' : '', script ? 'Откроется установка юзерскрипта в Tampermonkey.' : ''].filter(Boolean).join(' ');
    panel.els.updatePrompt.classList.add('open');
    GM_setValue('updatePromptedVersion', version);
    showPanel();
  }

  function wireSettings(q) {
    const get = (name) => q(`.${name}`);
    for (const key of ['highlightChunk', 'highlightWords', 'followScroll']) {
      get(key).addEventListener('change', (e) => {
        GM_setValue(key, e.target.checked);
        if (key === 'highlightChunk') {
          if (e.target.checked && isActive()) showHighlight(rangeForSpan(P.doc, P.chunks[P.index].s, P.chunks[P.index].e));
          else clearChunkHighlight();
        }
        if (key === 'highlightWords') { if (e.target.checked) startTicker(); else stopTicker(); }
        if (key === 'followScroll' && e.target.checked) { P.follow = true; followScroll(); }
      });
    }
    for (const key of ['chunkColor', 'wordColor']) get(key).addEventListener('input', (e) => {
      GM_setValue(key, e.target.value); ensureHighlightStyle();
    });
    for (const key of ['panelCorner', 'panelX', 'panelY']) get(key).addEventListener('change', (e) => {
      GM_setValue(key, e.target.value); panelPosition();
    });
    get('resetPosition').onclick = () => {
      GM_setValue('panelCorner', 'bottom-right'); GM_setValue('panelX', 16); GM_setValue('panelY', 16);
      get('panelCorner').value = 'bottom-right'; get('panelX').value = 16; get('panelY').value = 16;
      panelPosition();
    };
    get('prefetch').onchange = (e) => { GM_setValue('prefetch', Number(e.target.value)); if (isActive()) pump(); };
    get('voice').onchange = (e) => { GM_setValue('voice', e.target.value); invalidateFutureAudio(); };
    get('defaultRate').onchange = (e) => {
      const value = Math.min(RATE_MAX, Math.max(RATE_MIN, Number(e.target.value) || 1));
      GM_setValue('rate', value); P.rate = value; if (P.activeEl) P.activeEl.playbackRate = value;
      e.target.value = value.toFixed(1); updatePanel();
    };
    get('hotkey').onclick = openHotkeyCapture;
    get('saveServer').onclick = () => {
      const url = get('baseUrl').value.trim().replace(/\/$/, '');
      if (!/^http:\/\/(127\.0\.0\.1|localhost):\d{2,5}$/.test(url)) {
        setSettingsMessage('.health', 'Адрес должен вести на localhost.'); return;
      }
      GM_setValue('baseUrl', url); GM_setValue('token', get('token').value.trim()); checkServer();
    };
    get('checkServer').onclick = () => { get('saveServer').click(); };
    get('openSetup').onclick = () => window.open(`${baseUrl()}/setup`, '_blank', 'noopener');
    get('addDict').onclick = () => { addDictRow(); dictEdited(); };
    get('importDict').onclick = () => { get('dictFile').value = ''; get('dictFile').click(); };
    get('dictFile').onchange = (e) => importDictFile(e.target.files[0]);
    get('saveDict').onclick = saveDict;
    get('checkUpdate').onclick = () => checkUpdates();
  }

  function openSettings() {
    buildPanel(); showPanel(); panel.settings = true;
    panel.els.settings.classList.add('open');
    const q = (selector) => panel.root.querySelector(selector);
    q('.baseUrl').value = baseUrl(); q('.token').value = GM_getValue('token', '');
    q('.hotkey').textContent = describeHotkey(loadHotkey());
    q('.defaultRate').value = Number(GM_getValue('rate', 1)).toFixed(1);
    q('.voice').replaceChildren();
    for (const key of ['highlightChunk', 'highlightWords', 'followScroll']) q(`.${key}`).checked = GM_getValue(key, true) !== false;
    q('.chunkColor').value = GM_getValue('chunkColor', '') || '#ffd600';
    q('.wordColor').value = GM_getValue('wordColor', '') || '#ff8a00';
    q('.prefetch').value = String(prefetch());
    q('.panelCorner').value = GM_getValue('panelCorner', 'bottom-right');
    q('.panelX').value = GM_getValue('panelX', 16); q('.panelY').value = GM_getValue('panelY', 16);
    if (GM_getValue('token', '')) checkServer();
  }

  function closeSettings() {
    panel.settings = false; panel.els.settings.classList.remove('open');
    if (!isActive()) hidePanel(3000);
  }

  function showPanel() {
    buildPanel();
    clearTimeout(panel.hideTimer);
    panel.hideTimer = null;
    panel.host.style.setProperty('display', 'block', 'important');
    setNote('');
  }

  function hidePanel(delay) {
    if (!panel.host || panel.settings || panel.pendingUpdate || !panel.els.compatibility.hidden) return;
    clearTimeout(panel.hideTimer);
    if (!delay) { panel.host.style.setProperty('display', 'none', 'important'); return; }
    panel.hideTimer = setTimeout(() => {
      if (!panel.settings && !panel.pendingUpdate && panel.els.compatibility.hidden &&
          (P.state === 'idle' || P.state === 'ended')) panel.host.style.setProperty('display', 'none', 'important');
    }, delay);
  }

  function setNote(text) {
    if (panel.els) panel.els.note.textContent = text || '';
  }

  const GLYPHS = { playing: '⏸', paused: '▶', loading: '…', buffering: '…', ended: '▶', idle: '▶' };

  function updatePanel() {
    if (!panel.els) return;
    const total = P.chunks.length;
    panel.els.pos.textContent = total ? `${P.index + 1} / ${total}` : '— / —';
    panel.els.rate.textContent = `${P.rate.toFixed(1)}×`;
    panel.els.play.textContent = GLYPHS[P.state] || '▶';
    panel.els.spinner.classList.toggle('on', P.state === 'loading' || P.state === 'buffering');
    panel.els.prev.disabled = !total;
    panel.els.next.disabled = !total || P.index >= total - 1;
    panel.els.slower.disabled = P.rate <= RATE_MIN + 1e-6;
    panel.els.faster.disabled = P.rate >= RATE_MAX - 1e-6;
  }

  // ==== 8. Плеер =========================================================
  //
  //   idle → loading → playing ⇄ paused
  //                       ↓
  //                     ended → idle
  //
  // Очередей две, и путать их нельзя. Очередь запросов держит PREFETCH чанков
  // впереди играющего и знает свои abort'ы. Очередь воспроизведения играет
  // чанк i и по ended берёт i+1; если звука ещё нет — встаёт в buffering.

  const P = {
    state: 'idle',
    doc: null,
    chunks: [],
    index: 0,
    audio: new Map(),     // index → {url, el}
    reqs: new Map(),      // index → {abort, token, attempt}
    failed: new Set(),
    failures: 0,          // подряд, сбрасывается любым успехом
    activeEl: null,
    seekTimer: null,
    gapTimer: null,       // пауза между абзацами
    gapPending: false,    // паузу между абзацами прервали кнопкой «пауза»
    retryTimers: new Set(),
    rate: 1.0,
    sourceText: '',
    follow: true,
    generation: 0,        // растёт на каждый stop(): отсекает опоздавшие ответы
    portScanTried: false,
    discovering: null,
  };
  let recovery = null;

  function setState(state) {
    P.state = state;
    updatePanel();
  }

  function isActive() { return P.state !== 'idle' && P.state !== 'ended'; }

  // --- звук: хранение и освобождение ---
  //
  // Блобы текут — подтверждённая практикой грабля: сотня запросов подбирается
  // к гигабайту (README соседнего проекта Alkohole/machine-reading-text).
  // Поэтому в памяти живут ровно PREFETCH+1 кусков, а освобождение — это не
  // только revokeObjectURL, но и removeAttribute('src') + load(): без него
  // декодированный буфер остаётся висеть внутри самого элемента.

  function releaseEntry(entry) {
    if (!entry) return;
    const el = entry.el;
    el.onended = null;
    el.onerror = null;
    try { el.pause(); } catch (e) { /* ignore */ }
    try { el.removeAttribute('src'); el.load(); } catch (e) { /* ignore */ }
    try { URL.revokeObjectURL(entry.url); } catch (e) { /* ignore */ }
  }

  function releaseOutside(lo, hi) {
    for (const [i, entry] of [...P.audio]) {
      if (i >= lo && i <= hi) continue;
      if (entry.el === P.activeEl) continue;
      releaseEntry(entry);
      P.audio.delete(i);
    }
  }

  function releaseAll() {
    P.activeEl = null;
    for (const entry of P.audio.values()) releaseEntry(entry);
    P.audio.clear();
  }

  function invalidateFutureAudio() {
    if (!isActive()) return;
    for (const [i, req] of [...P.reqs]) {
      if (i <= P.index && P.activeEl) continue;
      try { req.abort(); } catch (e) { /* ignore */ }
      P.reqs.delete(i);
    }
    for (const [i, entry] of [...P.audio]) {
      if (entry.el === P.activeEl) continue;
      releaseEntry(entry); P.audio.delete(i);
    }
    pump();
  }

  // --- очередь запросов ---

  function abortAllRequests() {
    for (const req of P.reqs.values()) {
      try { req.abort(); } catch (e) { /* ignore */ }
    }
    P.reqs.clear();
    for (const t of P.retryTimers) clearTimeout(t);
    P.retryTimers.clear();
  }

  function pump() {
    if (!isActive()) return;
    const lo = P.index;
    const hi = Math.min(P.index + prefetch(), P.chunks.length - 1);
    for (const [i, req] of [...P.reqs]) {
      if (i < lo || i > hi) {
        try { req.abort(); } catch (e) { /* ignore */ }
        P.reqs.delete(i);
      }
    }
    releaseOutside(lo, hi);
    for (let i = lo; i <= hi; i++) {
      if (P.audio.has(i) || P.reqs.has(i) || P.failed.has(i)) continue;
      requestChunk(i, 0);
    }
  }

  function requestChunk(i, attempt) {
    const token = ensureToken();
    if (!token) { stopReading('Без токена читать нечем'); return; }
    const chunk = P.chunks[i];
    if (!chunk) return;
    const gen = P.generation;
    const req = { attempt, abort: () => {} };
    P.reqs.set(i, req);

    const stale = () => gen !== P.generation || P.reqs.get(i) !== req;

    const handle = GM_xmlhttpRequest({
      method: 'POST',
      url: `${baseUrl()}/tts`,
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      data: JSON.stringify({ text: chunk.text, voice: voice() }),
      responseType: 'arraybuffer',
      // Замерено в TTS-1: на входе около 5000 знаков модель не отказывает, а
      // молотит почти пять минут. Чанкинг такого не пришлёт, но если пришлёт
      // (или сервер встал на чужом запросе) — без таймаута очередь повиснет
      // без единого события. Холодный воркер отвечает за ~11 с, запас четырёхкратный.
      timeout: REQUEST_TIMEOUT,
      onload: (res) => {
        if (stale()) return;
        P.reqs.delete(i);
        if (res.status === 200 && res.response) {
          P.failures = 0;
          storeAudio(i, res.response, parseTimings(res.responseHeaders));
          return;
        }
        onHttpFailure(i, attempt, res.status || 0);
      },
      onerror: () => {
        if (stale()) return;
        P.reqs.delete(i);
        onHttpFailure(i, attempt, 0);
      },
      ontimeout: () => {
        if (stale()) return;
        P.reqs.delete(i);
        onHttpFailure(i, attempt, 0);
      },
      onabort: () => { if (!stale()) P.reqs.delete(i); },
    });
    if (handle && typeof handle.abort === 'function') req.abort = () => handle.abort();
  }

  function onHttpFailure(i, attempt, status) {
    if ((status === 0 || status === 401) && (P.discovering || !P.portScanTried)) {
      P.portScanTried = true;
      const gen = P.generation;
      const slot = { abort: () => {} };
      P.reqs.set(i, slot);
      if (!P.discovering) P.discovering = discoverServer(GM_getValue('token', ''));
      P.discovering.then(() => {
        if (gen !== P.generation || !isActive() || P.reqs.get(i) !== slot) return;
        P.reqs.delete(i);
        P.discovering = null;
        requestChunk(i, attempt);
      }).catch(() => {
        if (gen !== P.generation || !isActive() || P.reqs.get(i) !== slot) return;
        P.reqs.delete(i);
        P.discovering = null;
        if (status === 401) { stopReading('Неверный ключ'); openSettings(); }
        else showServerUnavailable();
      });
      return;
    }
    if (status === 401) {
      stopReading('Неверный ключ');
      openSettings();
      return;
    }
    if (status === 422) {
      stopReading('Сервер не знает такой голос');
      return;
    }
    if (status === 413 || status === 400) {
      // Чанкинг обязан был уложиться в предохранитель сервера. Раз не уложился —
      // это наш баг, а не временный сбой: повторять бессмысленно.
      failChunk(i, `Кусок ${i + 1} сервер не принял (${status})`);
      return;
    }
    // Всё остальное — одна повторная попытка через секунду. Ожидание повтора
    // занимает место в очереди запросов наравне с живым запросом: иначе
    // pump(), позванный за эту секунду кем-то ещё, увидит «чанк не запрошен»
    // и заведёт вторую попытку с нуля. Тогда attempt никогда не дорастёт до
    // единицы, счётчик подряд идущих ошибок не сдвинется, и при мёртвом
    // сервере чтение молча зависнет в buffering навсегда — ровно то, что
    // §7 запрещает.
    if (attempt < 1) {
      const slot = { abort: () => { clearTimeout(timer); P.retryTimers.delete(timer); } };
      const timer = setTimeout(() => {
        P.retryTimers.delete(timer);
        if (!isActive() || P.reqs.get(i) !== slot) return;
        P.reqs.delete(i);
        requestChunk(i, attempt + 1);
      }, RETRY_DELAY);
      P.retryTimers.add(timer);
      P.reqs.set(i, slot);
      return;
    }
    P.failures++;
    if (P.failures >= MAX_FAILURES) {
      // Молча вставать нельзя: человек слушает и на экран не смотрит.
      stopReading('Сервер чтеца отвалился — чтение остановлено');
      GM_notification('SKAZ: сервер не отвечает, чтение остановлено');
      return;
    }
    failChunk(i, `Кусок ${i + 1} не пришёл — пропущен`);
  }

  // Пропустить чанк и читать дальше — и обязательно сказать об этом.
  function failChunk(i, note) {
    P.failed.add(i);
    setNote(note);
    if (i !== P.index) { pump(); return; }
    if (P.state === 'paused') { pump(); return; }
    gotoChunk(i + 1, true);
  }

  // Тайминги приезжают заголовком рядом с телом-WAV: [[начало, конец,
  // смещение в тексте чанка, длина], …], времена в секундах по исходной
  // шкале аудио. Нет заголовка (старый сервер, чужой прокси) — просто
  // не будет пословной подсветки, чанковая не зависит ни от чего.
  function parseTimings(headers) {
    const m = TIMINGS_HEADER_RE.exec(headers || '');
    if (!m) return null;
    try {
      const bin = atob(m[1]);
      const bytes = new Uint8Array(bin.length);
      for (let k = 0; k < bin.length; k++) bytes[k] = bin.charCodeAt(k);
      const data = JSON.parse(new TextDecoder('utf-8').decode(bytes));
      return Array.isArray(data.w) && data.w.length ? data.w : null;
    } catch (e) {
      return null;   // подсветка — украшение, из-за неё чтение не срывается
    }
  }

  // --- очередь воспроизведения ---

  function storeAudio(i, arrayBuffer, words) {
    const url = URL.createObjectURL(new Blob([arrayBuffer], { type: 'audio/wav' }));
    const el = new Audio();
    el.preload = 'auto';
    el.src = url;
    try { el.load(); } catch (e) { /* ignore */ }
    P.audio.set(i, { url, el, words: words || null });
    if (i === P.index && (P.state === 'loading' || P.state === 'buffering')) {
      playCurrent();
      return;
    }
    pump();
  }

  // Пауза на стыке абзацев. Живёт таймером, а не тишиной в WAV: тишину в
  // конце куска пришлось бы синтезировать (и потом объяснять её TTS-7A,
  // который ищет паузы по RMS), а таймер точен и ничего не стоит.
  function startGap(ms) {
    clearGap();
    const gen = P.generation;
    P.gapTimer = setTimeout(() => {
      P.gapTimer = null;
      if (gen !== P.generation || !isActive() || P.state !== 'playing') return;
      gotoChunk(P.index + 1, true);
    }, ms);
  }

  function clearGap() {
    if (P.gapTimer) { clearTimeout(P.gapTimer); P.gapTimer = null; }
  }

  function detachActive() {
    stopTicker();
    const el = P.activeEl;
    if (!el) return;
    P.activeEl = null;
    el.onended = null;
    el.onerror = null;
    try { el.pause(); } catch (e) { /* ignore */ }
  }

  // --- тикер пословной подсветки (TTS-7A) ---
  //
  // requestAnimationFrame, а не setInterval: привязан к кадрам, даёт ~16 мс
  // точности даром и сам замирает в фоновой вкладке. Range строится только
  // при смене слова — пересоздавать его каждый кадр значило бы класть на
  // страницу лишнюю работу 60 раз в секунду ради одинаковой картинки.
  //
  // Скорость воспроизведения пересчёта не требует вовсе: playbackRate не
  // трогает currentTime, он идёт по исходной шкале аудио — той самой, в
  // которой сервер посчитал тайминги.

  let tickerId = 0;
  let tickerWord = -1;

  function wordsEnabled() { return GM_getValue('highlightWords', true) !== false; }

  // Слова идут по порядку, и время почти всегда чуть больше прошлого —
  // поэтому сначала шаг вперёд от текущего слова, и только на скачке
  // (перемотка, новый чанк, возврат назад) полный двоичный поиск.
  function wordAt(words, t, from) {
    if (from >= 0 && from < words.length && words[from][0] <= t) {
      let k = from;
      while (k + 1 < words.length && words[k + 1][0] <= t) k++;
      return k;
    }
    let lo = 0;
    let hi = words.length - 1;
    let best = -1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (words[mid][0] <= t) { best = mid; lo = mid + 1; } else hi = mid - 1;
    }
    return best;   // -1 — звук ещё в начальной тишине, подсвечивать нечего
  }

  function paintWord(words, k) {
    const chunk = P.chunks[P.index];
    if (k < 0 || !chunk) { clearWordHighlight(); return; }
    const w = words[k];
    showWordHighlight(rangeForSpan(P.doc, chunk.s + w[2], chunk.s + w[2] + w[3]));
  }

  function tick() {
    tickerId = 0;
    const el = P.activeEl;
    if (!el || P.state !== 'playing') return;
    const entry = P.audio.get(P.index);
    const words = entry && entry.words;
    if (words) {
      const k = wordAt(words, el.currentTime, tickerWord);
      if (k !== tickerWord) {
        tickerWord = k;
        paintWord(words, k);
      }
    }
    tickerId = requestAnimationFrame(tick);
  }

  function startTicker(keepWord) {
    stopTicker(keepWord);
    if (!keepWord) tickerWord = -1;
    if (!wordsEnabled() || !highlightSupported) return;
    if (!P.activeEl) return;
    tickerId = requestAnimationFrame(tick);
  }

  // keepPaint — это пауза: подсветка обязана остаться там, где остановился
  // звук, а не исчезнуть до возобновления.
  function stopTicker(keepPaint) {
    if (tickerId) { cancelAnimationFrame(tickerId); tickerId = 0; }
    if (keepPaint) return;
    tickerWord = -1;
    clearWordHighlight();
  }

  function playCurrent() {
    const i = P.index;
    const entry = P.audio.get(i);
    if (!entry) {
      detachActive();
      setState('buffering');
      pump();
      return;
    }
    detachActive();
    const el = entry.el;
    P.activeEl = el;
    el.playbackRate = P.rate;
    if (el.currentTime) { try { el.currentTime = 0; } catch (e) { /* ignore */ } }
    el.onended = () => {
      if (P.activeEl !== el) return;
      const gap = P.chunks[i] ? P.chunks[i].pause : 0;
      if (gap) startGap(gap);
      else gotoChunk(P.index + 1, true);
    };
    el.onerror = () => { if (P.activeEl === el) failChunk(i, `Кусок ${i + 1} не проигрался`); };
    setState('playing');
    const p = el.play();
    if (p && typeof p.catch === 'function') {
      p.catch((err) => {
        if (P.activeEl !== el) return;
        if (err && err.name === 'NotAllowedError') {
          detachActive();
          setState('paused');
          setNote('Браузер заблокировал звук — нажми ▶');
        }
      });
    }
    startTicker();
    pump();
  }

  function gotoChunk(i, autoplay) {
    clearGap();
    P.gapPending = false;
    while (i < P.chunks.length && P.failed.has(i)) i++;
    if (i >= P.chunks.length) { finishReading(); return; }
    P.index = i;
    const chunk = P.chunks[i];
    showHighlight(rangeForSpan(P.doc, chunk.s, chunk.e));
    followScroll();
    updatePanel();
    releaseOutside(P.index, P.index + prefetch());
    pump();
    if (autoplay) playCurrent();
    else { detachActive(); setState('paused'); }
  }

  function finishReading() {
    detachActive();
    abortAllRequests();
    releaseAll();
    setState('ended');
    setNote('Прочитано');
    // Подсветку снимаем не сразу: конец главы приятнее видеть. Поколение
    // сверяем, иначе таймер затрёт чтение, начатое за эти две с половиной
    // секунды.
    const gen = P.generation;
    setTimeout(() => {
      if (gen !== P.generation || P.state !== 'ended') return;
      clearHighlight();
      resetReading();
      setState('idle');
    }, 2500);
    hidePanel(3000);
  }

  function resetReading() {
    P.doc = null;
    P.chunks = [];
    P.index = 0;
    P.failed.clear();
    P.failures = 0;
    P.sourceText = '';
    P.follow = true;
    P.gapPending = false;
  }

  function stopReading(note) {
    P.generation++;
    recovery = null;
    clearTimeout(P.seekTimer);
    P.seekTimer = null;
    clearGap();
    abortAllRequests();
    detachActive();
    releaseAll();
    clearHighlight();
    resetReading();
    setState('idle');
    if (panel.els) {
      panel.els.startServer.hidden = true;
      panel.els.install.hidden = true;
    }
    if (note) { showPanel(); setNote(note); updatePanel(); hidePanel(6000); }
    else hidePanel(0);
  }

  function showInstallHelp() {
    panel.els.install.href = `https://github.com/${GITHUB_REPO}#установка`;
    panel.els.install.hidden = false;
  }

  function showServerUnavailable() {
    const pending = { doc: P.doc, startAt: P.chunks[P.index]?.s || 0, sourceText: P.sourceText };
    stopReading();
    recovery = pending;
    showPanel();
    setNote('Сервер не отвечает');
    panel.els.startServer.hidden = false;
    showInstallHelp();
  }

  async function healthAfterLaunch(token) {
    const urls = [baseUrl(), ...Array.from({ length: 5 }, (_, i) => `http://127.0.0.1:${8756 + i}`)];
    const checks = await Promise.all([...new Set(urls)].map(async (url) => {
      try { await gmJson('GET', `${url}/health`, undefined, token, 900); return url; }
      catch (e) { return null; }
    }));
    return checks.find(Boolean) || null;
  }

  async function launchServer() {
    if (!recovery) return;
    const pending = recovery;
    const generation = P.generation;
    panel.els.startServer.hidden = true;
    panel.els.install.hidden = true;
    setNote('Запускаю сервер…');
    const frame = document.createElement('iframe');
    frame.hidden = true;
    (document.body || document.documentElement).appendChild(frame);
    frame.src = 'skaz://start';
    setTimeout(() => frame.remove(), 5000);
    for (let attempt = 0; attempt < 3; attempt++) {
      await new Promise((resolve) => setTimeout(resolve, 1000));
      if (generation !== P.generation || recovery !== pending) return;
      const url = await healthAfterLaunch(GM_getValue('token', ''));
      if (generation !== P.generation || recovery !== pending) return;
      if (url) {
        GM_setValue('baseUrl', url);
        recovery = null;
        showPanel();
        beginReading(pending.doc, pending.startAt, pending.sourceText, 'Не удалось продолжить чтение');
        return;
      }
    }
    setNote('Не удалось запустить. Если SKAZ не установлен, откройте README.txt из архива.');
    panel.els.startServer.hidden = false;
    showInstallHelp();
  }

  // --- управление ---

  function togglePause() {
    if (!isActive()) return;
    if (P.state === 'paused') {
      // Пауза застала нас в промежутке между абзацами: доигрывать нечего,
      // предыдущий кусок уже кончился — сразу едем дальше.
      if (P.gapPending) {
        P.gapPending = false;
        setState('playing');
        gotoChunk(P.index + 1, true);
        return;
      }
      const el = P.activeEl;
      if (el) {
        setState('playing');
        const p = el.play();
        if (p && typeof p.catch === 'function') p.catch(() => {});
        startTicker(true);   // продолжаем с того же слова, а не с начала чанка
      } else {
        playCurrent();
      }
      pump();
      return;
    }
    if (P.gapTimer) {
      clearGap();
      P.gapPending = true;
      setState('paused');
      return;
    }
    // Пауза посреди буферизации тоже пауза: продолжим, когда звук придёт.
    const el = P.activeEl;
    if (el) { try { el.pause(); } catch (e) { /* ignore */ } }
    stopTicker(true);   // подсветка слова остаётся там же, где остановился звук
    setState('paused');
  }

  // Alt+→ десять раз подряд не должен ни наложить куски друг на друга, ни
  // устроить шторм запросов: звук глохнет сразу, подсветка едет сразу, а
  // запрос и воспроизведение откладываются до конца серии нажатий.
  function jump(delta) {
    if (!isActive() || !P.chunks.length) return;
    const wasPaused = P.state === 'paused' && !P.gapPending;
    clearGap();
    P.gapPending = false;
    let i = P.index + delta;
    while (i >= 0 && i < P.chunks.length && P.failed.has(i)) i += (delta >= 0 ? 1 : -1);
    if (i < 0) i = 0;
    if (i >= P.chunks.length) i = P.chunks.length - 1;

    detachActive();
    P.index = i;
    const chunk = P.chunks[i];
    showHighlight(rangeForSpan(P.doc, chunk.s, chunk.e));
    followScroll();
    setState(wasPaused ? 'paused' : 'buffering');

    clearTimeout(P.seekTimer);
    P.seekTimer = setTimeout(() => {
      P.seekTimer = null;
      if (!isActive()) return;
      releaseOutside(P.index, P.index + prefetch());
      pump();
      if (P.state !== 'paused') playCurrent();
    }, SEEK_DEBOUNCE);
  }

  // Скорость меняется мгновенно и не требует перезапроса: и звук, и будущие
  // тайминги (TTS-7A) живут в исходной шкале.
  function nudgeRate(delta) {
    let rate = Math.round((P.rate + delta) * 10) / 10;
    rate = Math.min(RATE_MAX, Math.max(RATE_MIN, rate));
    P.rate = rate;
    GM_setValue('rate', rate);
    if (P.activeEl) P.activeEl.playbackRate = rate;
    updatePanel();
  }

  // --- старт ---

  // Общий финал обоих путей: откуда пришёл текст, дальше уже не важно.
  function beginReading(doc, startAt, sourceText, emptyNote) {
    const spans = chunkText(doc.text, doc.blocks);
    if (!spans.length) {
      stopReading(emptyNote);
      return;
    }

    let index = 0;
    if (startAt > 0) {
      while (index < spans.length - 1 && spans[index][1] <= startAt) index++;
      // Чтение с середины: первый звучащий чанк опять должен быть коротким,
      // иначе между хоткеем и звуком встанет целое предложение.
      const [s, e, pause] = spans[index];
      if (e - s > FIRST_CHUNK_MAX) {
        const parts = cutFirst(doc.text, [s, e]);
        if (parts.length === 2) {
          spans.splice(index, 1, [parts[0][0], parts[0][1], 0], [parts[1][0], parts[1][1], pause]);
        }
      }
    }

    P.doc = doc;
    P.chunks = spans.map(([s, e, pause]) => ({ s, e, pause, text: doc.text.slice(s, e) }));
    P.index = index;
    P.sourceText = sourceText;
    P.follow = true;
    P.portScanTried = false;
    P.discovering = null;
    ourScrollAt = -Infinity;

    const chunk = P.chunks[index];
    showHighlight(rangeForSpan(P.doc, chunk.s, chunk.e));
    followScroll();   // первое предложение тоже надо показать, а не ждать второго
    setState('loading');
    updatePanel();
    pump();
  }

  function readSelection(selection, selText) {
    // Спрашиваем ключ один раз здесь, а не из pump(): иначе первый же префетч
    // выкатит три окна prompt подряд.
    if (!ensureToken()) return;
    const range = selection.getRangeAt(0).cloneRange();
    stopReading();
    showPanel();

    const doc = buildFromRange(range);
    if (!doc || !doc.text.trim()) {
      stopReading('Не удалось разобрать выделение');
      return;
    }

    // Своё выделение убираем: синяя заливка браузера рисуется поверх
    // Highlight API, и подсветка предложения под ней просто не видна.
    try { selection.removeAllRanges(); } catch (e) { /* ignore */ }

    beginReading(doc, 0, selText, 'В выделении нет текста для чтения');
  }

  function readPage() {
    if (!ensureToken()) return;
    const t0 = performance.now();
    let found = articleContainer();
    let doc = buildFromPage(found);
    // Контейнер угадан неудачно (всё внутри оказалось скрытым или мусорным) —
    // лучше прочитать лишнее, чем промолчать.
    if ((!doc || doc.text.length < MIN_CONTAINER_TEXT) && found.el !== document.body && document.body) {
      cachedContainer = found = { el: document.body, m: found.m };
      doc = buildFromPage(found);
    }
    const spent = performance.now() - t0;

    stopReading();
    showPanel();
    if (!doc || !doc.text.trim()) {
      stopReading('На странице не нашлось текста для чтения');
      return;
    }
    const caret = caretOffset(doc);
    console.log(
      `[SKAZ] страница: ${doc.text.length} знаков, ${doc.blocks.length} блоков, ` +
      `сбор ${spent.toFixed(1)} мс`, found.el
    );
    beginReading(doc, blockStartAt(doc, caret), '', 'На странице не нашлось текста для чтения');
  }

  // ==== 9. Ввод ==========================================================

  function isEditableFocus() {
    const el = document.activeElement;
    if (!el) return false;
    if (panel.host && (el === panel.host || panel.host.contains(el))) return false;
    if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT') return true;
    return !!el.isContentEditable;
  }

  function panelHasFocus() {
    return !!(panel.host && document.activeElement === panel.host);
  }

  function matchesHotkey(e, hotkey) {
    return e.code === hotkey.code && e.altKey === hotkey.alt && e.ctrlKey === hotkey.ctrl &&
      e.shiftKey === hotkey.shift && e.metaKey === hotkey.meta;
  }

  // Хоткей во время чтения = пауза, а не новое чтение. Новое чтение
  // начинается только при новом выделении — решение из карты, оно неочевидно.
  // Ничего не выделено и не читаем — значит читаем страницу целиком.
  function triggerSpeak() {
    const selection = window.getSelection();
    const selText = selection ? selection.toString().replace(/\s+/g, ' ').trim() : '';
    if (isActive() && (!selText || selText === P.sourceText)) { togglePause(); return; }
    if (selText && selection.rangeCount) { readSelection(selection, selText); return; }
    readPage();
  }

  document.addEventListener('keydown', (e) => {
    if (panel.capturing) return;
    if (panelHasFocus()) {
      if (e.code === 'Escape') {
        e.preventDefault(); e.stopPropagation();
        if (panel.settings) closeSettings();
        else panel.host.blur();
      }
      return;
    }
    if (matchesHotkey(e, loadHotkey())) {
      if (isEditableFocus()) return;
      e.preventDefault();
      triggerSpeak();
      return;
    }
    if (!isActive()) return;
    if (isEditableFocus()) return;
    if (e.code === 'Escape' && !e.altKey && !e.ctrlKey && !e.metaKey) {
      e.preventDefault();
      stopReading();
      return;
    }
    if (!e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
    if (e.code === 'ArrowRight') { e.preventDefault(); jump(1); }
    else if (e.code === 'ArrowLeft') { e.preventDefault(); jump(-1); }
    else if (e.code === 'ArrowUp') { e.preventDefault(); nudgeRate(RATE_STEP); }
    else if (e.code === 'ArrowDown') { e.preventDefault(); nudgeRate(-RATE_STEP); }
  }, true);

  window.addEventListener('pagehide', () => { if (isActive()) stopReading(); });

  // ==== 10. Меню Tampermonkey ============================================

  // Разведка TTS-6 требовала проверить, что @require-обход из репозитория
  // Tampermonkey действительно возвращает параллельность GM_xmlhttpRequest.
  // Проверяется по порядку событий: при последовательном режиме второй
  // запрос даже не стартует, пока не завершился первый.
  function diagnoseParallel() {
    const token = ensureToken();
    if (!token) return;
    const t0 = performance.now();
    const log = [];
    let done = 0;
    const N = 3;
    const ms = () => Math.round(performance.now() - t0);

    for (let k = 0; k < N; k++) {
      GM_xmlhttpRequest({
        method: 'POST',
        url: `${baseUrl()}/tts`,
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
        data: JSON.stringify({ text: `Проба номер ${k + 1}.`, voice: voice() }),
        responseType: 'arraybuffer',
        onloadstart: () => log.push({ kind: 'start', k, at: ms() }),
        onload: () => { log.push({ kind: 'load', k, at: ms() }); finish(); },
        onerror: () => { log.push({ kind: 'error', k, at: ms() }); finish(); },
      });
    }

    function finish() {
      if (++done < N) return;
      const firstLoad = log.findIndex((e) => e.kind !== 'start');
      const startedBefore = log.slice(0, firstLoad < 0 ? log.length : firstLoad)
        .filter((e) => e.kind === 'start').length;
      const parallel = startedBefore >= 2;
      console.log(
        `[SKAZ] GM_xmlhttpRequest: ${parallel ? 'параллельно' : 'последовательно'} ` +
        `(до первого ответа стартовало ${startedBefore} из ${N})`,
        log.map((e) => `${e.kind}#${e.k}@${e.at}ms`).join('  ')
      );
      GM_notification(
        `GM_xhr: ${parallel ? 'параллельно' : 'ПОСЛЕДОВАТЕЛЬНО'} ` +
        `(${startedBefore}/${N} стартовали до первого ответа). Подробности в консоли.`
      );
    }
  }

  // Пословная подсветка — украшение поверх чанковой, и выключается
  // независимо от неё. Тайминги сервер считает в любом случае: экономия
  // там копеечная (десяток миллисекунд на чанк), а два кодовых пути ради
  // неё разъехались бы.
  function toggleWordHighlight() {
    const on = !wordsEnabled();
    GM_setValue('highlightWords', on);
    if (panel.root) panel.root.querySelector('.highlightWords').checked = on;
    if (on) startTicker();
    else stopTicker();
    GM_notification(`SKAZ: пословная подсветка ${on ? 'включена' : 'выключена'}`);
  }

  // Показать, как текст порезался на чанки, не синтезируя звук. Без выделения
  // разбирается страница целиком — тем же путём, каким её прочтёт хоткей.
  function diagnoseChunks() {
    const selection = window.getSelection();
    const selText = selection ? selection.toString().trim() : '';
    const t0 = performance.now();
    let doc;
    let where;
    if (selText && selection.rangeCount) {
      doc = buildFromRange(selection.getRangeAt(0).cloneRange());
      where = 'выделение';
    } else {
      const found = articleContainer();
      doc = buildFromPage(found);
      where = 'страница';
      console.log('[SKAZ] контейнер:', found.el);
    }
    const built = performance.now() - t0;
    if (!doc) { GM_notification('Не удалось разобрать текст'); return; }
    const t1 = performance.now();
    const spans = chunkText(doc.text, doc.blocks);
    const cut = performance.now() - t1;
    console.log(
      `[SKAZ] ${where}: ${doc.text.length} знаков, ${doc.blocks.length} блоков → ` +
      `${spans.length} чанков (сбор ${built.toFixed(1)} мс, резка ${cut.toFixed(1)} мс)`
    );
    console.table(spans.map(([s, e, pause], i) => ({
      '#': i + 1,
      'знаков': e - s,
      'бюджет': budget(doc.text, s, e),
      'пауза': pause || '',
      'текст': doc.text.slice(s, e),
    })));
    GM_notification(`${spans.length} чанков за ${built.toFixed(0)} мс, таблица в консоли`);
  }

  P.rate = Math.min(RATE_MAX, Math.max(RATE_MIN, Number(GM_getValue('rate', 1.0)) || 1.0));

  // Страница /setup сообщает о нажатии кнопки после открытия 60-секундного
  // окна. Ключ забирает именно юзерскрипт и кладёт в общее GM-хранилище.
  if (location.hostname === '127.0.0.1' && location.pathname === '/setup') {
    document.addEventListener('skaz-pair-ready', async () => {
      try {
        const data = await gmJson('GET', `${location.origin}/pair`);
        if (!data.token) throw new Error('Ключ не получен');
        GM_setValue('token', data.token);
        GM_setValue('baseUrl', location.origin);
        const status = document.getElementById('status');
        if (status) status.textContent = 'Браузер связан. Можно открыть страницу с текстом и нажать Alt+T.';
        if (panel.els) { panel.root.querySelector('.token').value = data.token; checkServer(); }
      } catch (e) {
        const status = document.getElementById('status');
        if (status) status.textContent = `Автоматическое связывание не удалось: ${e.message}. Скопируйте ключ вручную.`;
      }
    });
  }

  GM_registerMenuCommand('Настройки SKAZ', configureServer);
  GM_registerMenuCommand('Сменить горячую клавишу', openHotkeyCapture);
  GM_registerMenuCommand('Озвучить выделенное или страницу', triggerSpeak);
  GM_registerMenuCommand('Пословная подсветка: вкл/выкл', toggleWordHighlight);
  GM_registerMenuCommand('Диагностика: параллельность запросов', diagnoseParallel);
  GM_registerMenuCommand('Диагностика: показать чанки', diagnoseChunks);
  setTimeout(() => checkUpdates(true), 1500);
})();
