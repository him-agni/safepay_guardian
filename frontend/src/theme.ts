// Light and dark mode. The choice is stored per browser; until the visitor picks one, the device setting
// decides (and changes with it). index.html applies the theme before the app loads, so there is no flash.

import { useSyncExternalStore } from 'react'

export type Theme = 'light' | 'dark'

const KEY = 'safepay.theme'
const EVENT = 'safepay-theme'

function stored(): Theme | null {
  try {
    const v = localStorage.getItem(KEY)
    return v === 'light' || v === 'dark' ? v : null
  } catch {
    return null
  }
}

function system(): Theme {
  return typeof window !== 'undefined' && window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function currentTheme(): Theme {
  const t = document.documentElement.dataset.theme
  return t === 'dark' || t === 'light' ? t : (stored() ?? system())
}

function apply(theme: Theme) {
  document.documentElement.dataset.theme = theme
  document.documentElement.style.colorScheme = theme
  window.dispatchEvent(new Event(EVENT))
}

export function setTheme(theme: Theme) {
  try {
    localStorage.setItem(KEY, theme)
  } catch {
    // private mode: the choice lasts for this page only
  }
  apply(theme)
}

function subscribe(onChange: () => void) {
  const media = window.matchMedia?.('(prefers-color-scheme: dark)')
  const onSystem = () => {
    if (!stored()) apply(system())
  }
  window.addEventListener(EVENT, onChange)
  media?.addEventListener('change', onSystem)
  return () => {
    window.removeEventListener(EVENT, onChange)
    media?.removeEventListener('change', onSystem)
  }
}

/** The active theme; re-renders when the visitor or the device changes it. */
export function useTheme(): Theme {
  return useSyncExternalStore(subscribe, currentTheme, () => 'light')
}
