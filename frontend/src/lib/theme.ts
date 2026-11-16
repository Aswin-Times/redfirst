/**
 * Light / dark / system theme without a dependency. The choice is kept in localStorage and
 * applied as a `dark` class on <html>. THEME_SCRIPT runs before first paint (see layout.tsx)
 * so a saved choice never flashes the wrong theme. Every storage access is guarded: it can
 * throw in private windows or with blocked site data, and the app must still work.
 */

export type ThemeChoice = "system" | "light" | "dark";

export const THEME_KEY = "redfirst-theme";

export const parseTheme = (value: string | null | undefined): ThemeChoice =>
  value === "light" || value === "dark" ? value : "system";

export const resolveTheme = (choice: ThemeChoice, systemPrefersDark: boolean): "light" | "dark" =>
  choice === "system" ? (systemPrefersDark ? "dark" : "light") : choice;

/** Plain ES5 on purpose: it is inlined into the page and must not depend on the bundle. */
export const THEME_SCRIPT = `(function(){try{var c=localStorage.getItem("${THEME_KEY}");var d=c==="dark"||(c!=="light"&&window.matchMedia("(prefers-color-scheme: dark)").matches);var r=document.documentElement;r.classList.toggle("dark",d);r.style.colorScheme=d?"dark":"light"}catch(e){}})()`;

const SYSTEM_QUERY = "(prefers-color-scheme: dark)";
const listeners = new Set<() => void>();

const systemPrefersDark = () =>
  typeof window !== "undefined" && Boolean(window.matchMedia?.(SYSTEM_QUERY).matches);

export function readTheme(): ThemeChoice {
  try {
    return parseTheme(localStorage.getItem(THEME_KEY));
  } catch {
    return "system";
  }
}

export function applyTheme(choice: ThemeChoice): void {
  const dark = resolveTheme(choice, systemPrefersDark()) === "dark";
  const root = document.documentElement;
  root.classList.toggle("dark", dark);
  root.style.colorScheme = dark ? "dark" : "light";
}

export function saveTheme(choice: ThemeChoice): void {
  try {
    if (choice === "system") localStorage.removeItem(THEME_KEY);
    else localStorage.setItem(THEME_KEY, choice);
  } catch {
    // Storage is blocked: the choice still applies for this page view.
  }
  applyTheme(choice);
  listeners.forEach((notify) => notify());
}

/** For useSyncExternalStore: re-renders on saves, other tabs, and OS changes while on system. */
export const themeStore = {
  subscribe(notify: () => void) {
    listeners.add(notify);
    const media = window.matchMedia?.(SYSTEM_QUERY);
    const onSystem = () => {
      if (readTheme() === "system") applyTheme("system");
    };
    const onStorage = (e: StorageEvent) => {
      if (e.key !== THEME_KEY) return;
      applyTheme(readTheme());
      notify();
    };
    media?.addEventListener("change", onSystem);
    window.addEventListener("storage", onStorage);
    return () => {
      listeners.delete(notify);
      media?.removeEventListener("change", onSystem);
      window.removeEventListener("storage", onStorage);
    };
  },
  getSnapshot: readTheme,
  getServerSnapshot: (): ThemeChoice => "system",
};
