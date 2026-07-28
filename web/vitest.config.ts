import { defineConfig } from 'vitest/config'

// Separate from vite.config.ts so the app build config stays untouched. Only the
// pure logic in src/data is covered here, none of which needs the React plugin,
// a DOM, or a browser environment.
//
// `environment: 'node'` is fine even though openStatus.ts leans on Intl with a
// timeZone and on @holiday-jp/holiday_jp (a CommonJS package): Node 20+ ships
// full ICU, and Vite's dependency interop resolves the package's named exports
// the same way the browser build does.
export default defineConfig({
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
})
