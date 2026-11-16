import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  THEME_KEY, THEME_SCRIPT, applyTheme, parseTheme, readTheme, resolveTheme, saveTheme,
} from "@/lib/theme";

function stubSystemTheme(dark: boolean) {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: (media: string) => ({
      matches: dark, media, addEventListener() {}, removeEventListener() {},
    }),
  });
}

const isDark = () => document.documentElement.classList.contains("dark");

beforeEach(() => {
  localStorage.clear();
  document.documentElement.className = "";
  document.documentElement.style.colorScheme = "";
  stubSystemTheme(false);
});
afterEach(() => localStorage.clear());

describe("parseTheme", () => {
  it.each([["light", "light"], ["dark", "dark"], ["system", "system"], [null, "system"],
    [undefined, "system"], ["", "system"], ["purple", "system"]])("%j -> %s", (raw, want) => {
    expect(parseTheme(raw as string | null | undefined)).toBe(want);
  });
});

describe("resolveTheme", () => {
  it("follows the system only when the choice is system", () => {
    expect(resolveTheme("system", true)).toBe("dark");
    expect(resolveTheme("system", false)).toBe("light");
    expect(resolveTheme("light", true)).toBe("light");
    expect(resolveTheme("dark", false)).toBe("dark");
  });
});

describe("applyTheme and saveTheme", () => {
  it("sets the dark class and the browser's colour scheme", () => {
    applyTheme("dark");
    expect(isDark()).toBe(true);
    expect(document.documentElement.style.colorScheme).toBe("dark");
    applyTheme("light");
    expect(isDark()).toBe(false);
    expect(document.documentElement.style.colorScheme).toBe("light");
  });

  it("applies the system preference for the system choice", () => {
    stubSystemTheme(true);
    applyTheme("system");
    expect(isDark()).toBe(true);
  });

  it("remembers an explicit choice and forgets it for system", () => {
    saveTheme("dark");
    expect(localStorage.getItem(THEME_KEY)).toBe("dark");
    expect(readTheme()).toBe("dark");
    saveTheme("system");
    expect(localStorage.getItem(THEME_KEY)).toBeNull();
    expect(readTheme()).toBe("system");
  });

  it("still applies the theme when storage is blocked", () => {
    const original = Storage.prototype.setItem;
    Storage.prototype.setItem = () => {
      throw new Error("blocked");
    };
    try {
      expect(() => saveTheme("dark")).not.toThrow();
      expect(isDark()).toBe(true);
    } finally {
      Storage.prototype.setItem = original;
    }
  });
});

describe("THEME_SCRIPT (runs before first paint)", () => {
  const run = () => new Function(THEME_SCRIPT)();

  it("uses the stored choice over the system preference", () => {
    stubSystemTheme(true);
    localStorage.setItem(THEME_KEY, "light");
    run();
    expect(isDark()).toBe(false);
    stubSystemTheme(false);
    localStorage.setItem(THEME_KEY, "dark");
    run();
    expect(isDark()).toBe(true);
  });

  it("falls back to the system preference with nothing stored or something invalid", () => {
    stubSystemTheme(true);
    run();
    expect(isDark()).toBe(true);
    document.documentElement.className = "";
    localStorage.setItem(THEME_KEY, "purple");
    stubSystemTheme(false);
    run();
    expect(isDark()).toBe(false);
  });

  it("never throws, even if storage is unavailable", () => {
    const original = Storage.prototype.getItem;
    Storage.prototype.getItem = () => {
      throw new Error("blocked");
    };
    try {
      expect(run).not.toThrow();
    } finally {
      Storage.prototype.getItem = original;
    }
  });
});
