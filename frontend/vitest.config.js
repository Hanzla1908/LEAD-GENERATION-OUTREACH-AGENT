import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// Unit and integration tests. Every API call is answered by the in-memory fake backend through MSW,
// and unhandled requests fail the test, so nothing reaches a live API, a database or an email service.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    include: ['tests/unit/**/*.test.{js,jsx}', 'tests/integration/**/*.test.{js,jsx}'],
    exclude: ['node_modules', 'tests/e2e/**'],
    setupFiles: ['tests/setup/vitest.setup.js'],
    css: false,
    clearMocks: true,
    restoreMocks: true,
    testTimeout: 15000,
  },
})
