// Read a CSS custom property from :root. Theme-aware: returns the value
// currently resolved for the active data-theme. Falls back to the given
// default if the var is missing or document is unavailable (SSR safety).
export function cssVar(name, fallback = '') {
  try {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
    return v || fallback
  } catch {
    return fallback
  }
}
