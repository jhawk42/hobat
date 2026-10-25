import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const source = fs.readFileSync("src/js/tdash-theme.js", "utf8");
const uiSource = fs.readFileSync("src/js/tdash-ui.js", "utf8");
const bindingStart = uiSource.indexOf("function initAppearanceControls() {");
const bindingEnd = uiSource.indexOf("\ninitAppearanceControls();", bindingStart);
assert.ok(bindingStart >= 0 && bindingEnd > bindingStart);
const bindingSource = uiSource.slice(bindingStart, bindingEnd);
const key = "tdash.themePreference";
function boot({ saved = null, dark = false, readError = false, writeError = false, mediaMissing = false } = {}) {
  const events = [];
  const warnings = [];
  const listeners = new Map();
  const documentListeners = new Map();
  const media = { matches: dark, addEventListener(type, callback) { listeners.set(`media:${type}`, callback); } };
  const writes = [];
  const storage = {
    getItem(name) { assert.equal(name, key); if (readError) throw new Error("blocked read"); return saved; },
    setItem(name, value) { if (writeError) throw new Error("blocked write"); writes.push([name, value]); },
  };
  const root = { dataset: {}, style: {} };
  const context = vm.createContext({
    document: {
      documentElement: root,
      addEventListener(type, callback) { documentListeners.set(type, callback); },
      dispatchEvent(event) { events.push(event); documentListeners.get(event.type)?.(event); },
    },
    localStorage: storage,
    matchMedia: mediaMissing ? undefined : () => media,
    addEventListener(type, callback) { listeners.set(type, callback); },
    CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options.detail; } },
    console: { warn(...args) { warnings.push(args); }, error(...args) { warnings.push(args); } },
  });
  vm.runInContext(source, context);
  return {
    context, controller: context.tdashTheme, root, events, warnings, writes, listeners, documentListeners,
    os(next) { media.matches = next; listeners.get("media:change")(); },
    external(value, eventKey = key, storageArea = storage) {
      listeners.get("storage")({ key: eventKey, newValue: value, storageArea });
    },
  };
}

for (const dark of [false, true]) {
  for (const saved of [null, "system", "light", "dark"]) {
    const t = boot({ saved, dark });
    const expected = saved === null || saved === "system" ? (dark ? "dark" : "light") : saved;
    assert.equal(t.root.dataset.theme, expected);
    assert.equal(t.root.dataset.themePreference, saved ?? "system");
    assert.equal(t.root.style.colorScheme, expected);
    assert.ok(Object.isFrozen(t.controller));
    assert.ok(Object.isFrozen(t.controller.getState()));
    assert.equal(t.events.length, 1);
    assert.equal(t.writes.length, 0);
    t.os(!dark);
    assert.equal(t.controller.getState().resolvedTheme, saved === "light" || saved === "dark" ? saved : (!dark ? "dark" : "light"));
    assert.equal(t.writes.length, 0);
  }
}
const t = boot();
const originalController = t.controller;
vm.runInContext(source, t.context);
assert.equal(t.context.tdashTheme, originalController);
assert.equal(t.listeners.size, 2);
assert.equal(t.events.length, 1);
assert.throws(() => t.controller.setPreference("invalid"), { name: "TypeError" });
t.controller.setPreference("dark");
const snapshot = t.controller.getState();
t.controller.setPreference("dark");
assert.equal(t.events.length, 2);
assert.equal(t.writes.length, 2);
assert.equal(snapshot, t.controller.getState());
t.external("light", "unrelated");
t.external("light", key, {});
assert.equal(t.controller.getState().preference, "dark");
t.external("light");
assert.equal(t.controller.getState().preference, "light");
t.external(null);
assert.equal(t.controller.getState().preference, "system");
t.external("dark");
t.external(null, null);
assert.equal(t.controller.getState().preference, "system");
assert.equal(t.writes.length, 2);
const invalid = boot({ saved: "bad", dark: true });
assert.equal(invalid.controller.getState().persistenceStatus, "invalid-value");
assert.equal(invalid.controller.getState().resolvedTheme, "dark");
invalid.external("also-bad");
assert.equal(invalid.warnings.length, 1);
invalid.controller.setPreference("light");
assert.equal(invalid.controller.getState().persistenceStatus, "ok");
const blocked = boot({ readError: true, writeError: true });
assert.equal(blocked.controller.getState().persistenceStatus, "unavailable");
blocked.controller.setPreference("dark");
assert.equal(blocked.controller.getState().preference, "dark");
assert.equal(blocked.controller.getState().persistenceStatus, "unavailable");
blocked.external("light");
assert.equal(blocked.controller.getState().persistenceStatus, "ok");
assert.equal(blocked.controller.getState().preference, "light");
const missing = boot({ mediaMissing: true });
assert.equal(missing.controller, undefined);
assert.equal(missing.root.dataset.theme, undefined);
assert.equal(missing.warnings.length, 1);

function bindControls(t) {
  const elements = new Map(["theme-toggle", "settings-theme-toggle", "theme-status", "settings-theme-status"]
    .map((id) => [id, {
      disabled: true, dataset: {}, attributes: {}, listeners: new Map(),
      icon: { textContent: "\u25d1" }, textContent: "",
      querySelector(selector) { assert.equal(selector, ".theme-toggle-icon"); return this.icon; },
      setAttribute(name, value) { this.attributes[name] = value; },
      addEventListener(type, callback) { this.listeners.set(type, callback); },
      click() { assert.equal(this.disabled, false); this.listeners.get("click")(); },
    }]));
  let applications = 0;
  t.context.document.getElementById = (id) => elements.get(id);
  t.context.readThemePalette = () => ({});
  t.context.getTopologyFilterHandlers = () => ({ applyTheme() { applications++; } });
  vm.runInContext(`${bindingSource}\ninitAppearanceControls();`, t.context);
  return {
    header: elements.get("theme-toggle"), settings: elements.get("settings-theme-toggle"),
    status: elements.get("theme-status"), settingsStatus: elements.get("settings-theme-status"),
    applications: () => applications,
  };
}
for (const dark of [false, true]) {
  const t = boot({ dark });
  const controls = bindControls(t);
  function expect(preference, symbol, label, next) {
    for (const button of [controls.header, controls.settings]) {
      assert.equal(button.disabled, false);
      assert.equal(button.dataset.themePreference, preference);
      assert.equal(button.icon.textContent, symbol);
      assert.equal(button.attributes["aria-label"], `Theme: ${label}. Switch to ${next}.`);
      assert.equal(button.title, button.attributes["aria-label"]);
      assert.equal(button.attributes["aria-pressed"], undefined);
      assert.equal(button.listeners.size, 1);
    }
  }
  expect("system", "\u25d1", `System (${dark ? "dark" : "light"})`, "Light");
  controls.header.click();
  expect("light", "\u263c", "Light", "Dark");
  controls.settings.click();
  expect("dark", "\u263e", "Dark", "System");
  controls.header.click();
  expect("system", "\u25d1", `System (${dark ? "dark" : "light"})`, "Light");
  t.os(!dark);
  expect("system", "\u25d1", `System (${dark ? "light" : "dark"})`, "Light");
  t.external("light");
  expect("light", "\u263c", "Light", "Dark");
  controls.settings.click();
  expect("dark", "\u263e", "Dark", "System");
  const applications = controls.applications();
  t.os(dark);
  assert.equal(controls.applications(), applications);
  t.external(null, null);
  expect("system", "\u25d1", `System (${dark ? "dark" : "light"})`, "Light");
  assert.equal(t.writes.length, 4);
  assert.equal(t.documentListeners.size, 1);
}
for (const [saved, symbol, next] of [["light", "\u263c", "dark"], ["dark", "\u263e", "system"]]) {
  const t = boot({ saved, dark: saved === "light" });
  const controls = bindControls(t);
  for (const button of [controls.header, controls.settings]) {
    assert.equal(button.dataset.themePreference, saved);
    assert.equal(button.icon.textContent, symbol);
  }
  controls.settings.click();
  assert.equal(t.controller.getState().preference, next);
}
const blockedControls = bindControls(boot({ readError: true, writeError: true }));
blockedControls.header.click();
assert.equal(blockedControls.header.icon.textContent, "\u263c");
assert.equal(blockedControls.status.textContent, "Theme applies to this page only. Browser storage is unavailable.");
assert.equal(blockedControls.settingsStatus.textContent, blockedControls.status.textContent);
const invalidControls = bindControls(boot({ saved: "bad" }));
assert.match(invalidControls.status.textContent, /Saved theme was not recognized/);
invalidControls.settings.click();
assert.equal(invalidControls.status.textContent, "");
assert.equal(invalidControls.settingsStatus.textContent, "");
const unavailable = boot({ mediaMissing: true });
const unavailableControls = bindControls(unavailable);
assert.equal(unavailableControls.header.disabled, true);
assert.equal(unavailableControls.settings.disabled, true);
assert.equal(unavailable.documentListeners.size, 0);
console.log("theme controller: passed");
