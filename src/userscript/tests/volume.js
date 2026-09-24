const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const source = fs.readFileSync(path.join(__dirname, '..', 'skaz.user.js'), 'utf8');

function section(start, end) {
  const from = source.indexOf(start);
  const to = source.indexOf(end, from);
  assert.ok(from >= 0 && to > from);
  return source.slice(from, to);
}

const volumeCode = section('  function clampVolume(', '  function panelPosition()');
const positionCode = section('  function panelPosition()', '  function buildPanel()');
const audioCode = section('  function audioUnavailable(', '  function releaseOutside(');
const releaseCode = section('  function releaseAll()', '  function invalidateFutureAudio()');

function harness(saved = new Map(), contextType) {
  const nodes = [];
  const revoked = [];
  const P = { audio: new Map(), activeEl: null, index: 0, audioContext: null, audioReady: null, playToken: 0 };
  const Audio = function () {
    return {
      volume: 1,
      preload: '',
      src: '',
      pause() { this.paused = true; },
      load() { this.loaded = true; },
      removeAttribute(name) { if (name === 'src') this.src = ''; },
    };
  };
  const window = { AudioContext: contextType, innerHeight: 300 };
  const URL = { revokeObjectURL(value) { revoked.push(value); } };
  const GM_getValue = (key, fallback) => saved.has(key) ? saved.get(key) : fallback;
  const GM_setValue = (key, value) => saved.set(key, value);
  const code = `${volumeCode}\n${positionCode}\n${audioCode}\n${releaseCode}\nreturn { volume, panel, P, clampVolume, volumeGain, setVolume, toggleMute, applyVolume, panelPosition, openVolumeControl, initAudioContext, prepareEntryAudio, releaseEntry, releaseAll };`;
  const api = new Function('P', 'window', 'URL', 'Audio', 'GM_getValue', 'GM_setValue', 'nodes', code)(
    P, window, URL, Audio, GM_getValue, GM_setValue, nodes
  );
  return { ...api, saved, nodes, revoked, Audio };
}

function workingContext(nodes) {
  return class {
    constructor() {
      this.state = 'running';
      this.destination = { kind: 'destination' };
    }
    resume() { return Promise.resolve(); }
    createMediaElementSource(el) {
      const node = { kind: 'source', el, links: [], connect(target) { this.links.push(target); }, disconnect() { this.links = []; this.disconnected = true; } };
      nodes.push(node);
      return node;
    }
    createGain() {
      const node = { kind: 'gain', gain: { value: 1 }, links: [], connect(target) { this.links.push(target); }, disconnect() { this.links = []; this.disconnected = true; } };
      nodes.push(node);
      return node;
    }
    close() { this.closed = true; return Promise.resolve(); }
  };
}

async function run() {
  const saved = new Map();
  const nodes = [];
  const app = harness(saved, workingContext(nodes));
  assert.equal(app.volume.level, 100);
  assert.equal(app.volumeGain(), 1);
  assert.equal(app.clampVolume(-5), 0);
  assert.equal(app.clampVolume(250), 200);
  assert.equal(app.clampVolume('broken'), 100);
  assert.match(source, /class="volume-slider"[^>]*min="0" max="200" step="1" value="100"/);
  assert.match(source, /\.volume-middle \{[^}]*top:50%/);
  const popupStyle = source.match(/\.volume-popup \{[^}]+\}/)[0];
  assert.match(popupStyle, /left:0/);
  assert.match(popupStyle, /width:36px/);
  assert.doesNotMatch(popupStyle, /background|box-shadow/);
  assert.match(source, /\.volume-track \{[^}]*width:36px/);
  assert.match(source, /class="volume-button"[^>]*><svg/);
  assert.doesNotMatch(source, /🔊|🔇/);

  function element() {
    const classes = new Set();
    const properties = new Map();
    return {
      classList: {
        add(name) { classes.add(name); },
        contains(name) { return classes.has(name); },
        toggle(name, enabled) { if (enabled) classes.add(name); else classes.delete(name); },
      },
      style: { setProperty(name, value) { properties.set(name, value); }, getPropertyValue(name) { return properties.get(name); } },
    };
  }
  const layout = element();
  const control = element();
  const popup = element();
  const button = { getBoundingClientRect() { return { top: 120, bottom: 156 }; } };
  app.panel.host = element();
  app.panel.root = { querySelector(selector) { return selector === '.panel-layout' ? layout : control; }, activeElement: null };
  app.panel.els = { volumeControl: control, volumeButton: button, volumePopup: popup };
  control.classList.add('open');
  for (const corner of ['top-left', 'top-right', 'bottom-left', 'bottom-right']) {
    saved.set('panelCorner', corner);
    saved.set('panelX', 0);
    saved.set('panelY', 16);
    app.panelPosition();
    assert.equal(layout.classList.contains('left'), corner.endsWith('left'));
    assert.equal(layout.classList.contains('right'), corner.endsWith('right'));
    assert.equal(layout.classList.contains('bottom'), corner.startsWith('bottom'));
    assert.equal(control.classList.contains('bottom'), corner.startsWith('bottom'));
    assert.equal(app.panel.host.style.getPropertyValue(corner.endsWith('left') ? 'left' : 'right'), '0px');
    assert.equal(popup.style.getPropertyValue('--volume-height'), corner.startsWith('bottom') ? '72px' : '96px');
  }
  app.panel.els = null;

  app.initAudioContext();
  await app.P.audioReady;
  const first = { url: 'first', el: new app.Audio() };
  app.P.audio.set(0, first);
  app.P.activeEl = first.el;
  app.prepareEntryAudio(first);
  assert.equal(first.gain.gain.value, 1);
  assert.deepEqual(first.source.links, [first.gain]);
  assert.deepEqual(first.gain.links, [app.P.audioContext.destination]);

  app.setVolume(200);
  assert.equal(first.gain.gain.value, 2);
  assert.equal(saved.get('volume'), 200);
  const second = { url: 'second', el: new app.Audio() };
  app.P.audio.set(1, second);
  app.prepareEntryAudio(second);
  assert.equal(second.gain.gain.value, 2);

  app.toggleMute();
  assert.equal(first.gain.gain.value, 0);
  assert.equal(app.volume.level, 200);
  app.toggleMute();
  assert.equal(first.gain.gain.value, 2);
  app.setVolume(0);
  assert.equal(first.gain.gain.value, 0);
  app.toggleMute();
  assert.equal(app.volume.level, 200);
  assert.equal(first.gain.gain.value, 2);

  app.releaseEntry(first);
  app.P.audio.delete(0);
  assert.equal(first.source, null);
  assert.equal(first.gain, null);
  assert.ok(nodes[0].disconnected);
  assert.ok(nodes[1].disconnected);
  assert.deepEqual(app.revoked, ['first']);
  app.releaseAll();
  assert.equal(app.P.audio.size, 0);
  assert.equal(app.P.audioContext, null);
  assert.ok(nodes[2].disconnected);
  assert.ok(nodes[3].disconnected);
  assert.deepEqual(app.revoked, ['first', 'second']);

  const nextPage = harness(saved);
  assert.equal(nextPage.volume.level, 200);
  assert.equal(nextPage.volume.muted, false);

  const limited = harness(new Map(), null);
  limited.initAudioContext();
  limited.setVolume(200);
  const direct = { url: 'direct', el: new limited.Audio() };
  limited.prepareEntryAudio(direct);
  assert.equal(limited.volume.limited, true);
  assert.equal(direct.el.volume, 1);
  limited.toggleMute();
  limited.P.activeEl = direct.el;
  limited.applyVolume();
  assert.equal(direct.el.volume, 0);

  const brokenNodes = [];
  class BrokenGraph extends workingContext(brokenNodes) {
    createGain() { throw new Error('gain unavailable'); }
  }
  const broken = harness(new Map(), BrokenGraph);
  broken.initAudioContext();
  await broken.P.audioReady;
  broken.setVolume(200);
  const brokenEntry = { url: 'broken', el: new broken.Audio() };
  const originalEl = brokenEntry.el;
  broken.prepareEntryAudio(brokenEntry);
  assert.equal(broken.volume.limited, true);
  assert.notEqual(brokenEntry.el, originalEl);
  assert.equal(brokenEntry.el.volume, 1);
  assert.ok(brokenNodes[0].disconnected);

  class RejectedContext extends workingContext([]) {
    resume() { return Promise.reject(new Error('resume unavailable')); }
  }
  const rejected = harness(new Map(), RejectedContext);
  rejected.initAudioContext();
  await rejected.P.audioReady;
  assert.equal(rejected.P.audioContext, null);
  assert.equal(rejected.volume.limited, true);
}

run().then(() => console.log('volume OK'), (error) => { console.error(error); process.exitCode = 1; });
