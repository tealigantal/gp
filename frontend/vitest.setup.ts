import '@testing-library/jest-dom/vitest'

// antd responsive uses matchMedia; provide minimal polyfill for jsdom
if (!('matchMedia' in window)) {
  // @ts-expect-error - define for tests
  window.matchMedia = (query: string) => ({
    media: query,
    matches: false,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })
}
