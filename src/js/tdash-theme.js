(() => {
  "use strict";

  if (globalThis.tdashTheme) return;
  const root = document.documentElement;
  if (typeof globalThis.matchMedia !== "function") {
    console.error("Appearance control unavailable: matchMedia is unavailable.");
    return;
  }
  const key = "tdash.themePreference";
  const modes = new Set(["system", "light", "dark"]);
  const media = globalThis.matchMedia("(prefers-color-scheme: dark)");
  let warnedInvalid = false;
  let state;
  let storage;

  function parse(value) {
    if (value === null || modes.has(value)) {
      return { preference: value ?? "system", persistenceStatus: "ok" };
    }
    if (!warnedInvalid) {
      console.warn("Saved theme was not recognized. Using System; choose a theme to save it.");
      warnedInvalid = true;
    }
    return { preference: "system", persistenceStatus: "invalid-value" };
  }

  function apply(preference, persistenceStatus) {
    const resolvedTheme = preference === "system" ? (media.matches ? "dark" : "light") : preference;
    if (state?.preference === preference
      && state.resolvedTheme === resolvedTheme
      && state.persistenceStatus === persistenceStatus) return state;
    state = Object.freeze({ preference, resolvedTheme, persistenceStatus });
    root.dataset.theme = resolvedTheme;
    root.dataset.themePreference = preference;
    root.style.colorScheme = resolvedTheme;
    document.dispatchEvent(new CustomEvent("tdash:theme-changed", { detail: state }));
    return state;
  }

  let initial;
  try {
    storage = globalThis.localStorage;
    initial = parse(storage.getItem(key));
  } catch (error) {
    console.warn("Theme storage is unavailable.", error);
    initial = { preference: "system", persistenceStatus: "unavailable" };
  }
  apply(initial.preference, initial.persistenceStatus);

  globalThis.tdashTheme = Object.freeze({
    getState: () => state,
    setPreference(value) {
      if (!modes.has(value)) throw new TypeError("Theme must be system, light, or dark.");
      let persistenceStatus = "ok";
      try {
        storage = globalThis.localStorage;
        storage.setItem(key, value);
      } catch (error) {
        persistenceStatus = "unavailable";
        console.warn("Theme applies to this page only. Browser storage is unavailable.", error);
      }
      return apply(value, persistenceStatus);
    },
  });

  media.addEventListener("change", () => {
    if (state.preference === "system") apply(state.preference, state.persistenceStatus);
  });
  globalThis.addEventListener("storage", (event) => {
    if (event.storageArea !== storage || !storage || (event.key !== key && event.key !== null)) return;
    const next = parse(event.key === null ? null : event.newValue);
    apply(next.preference, next.persistenceStatus);
  });
})();
