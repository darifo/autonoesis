import { defineConfig } from "@playwright/test";

const testPort = 4174;

export default defineConfig({
  testDir: "./tests",
  use: { baseURL: `http://127.0.0.1:${testPort}` },
  webServer: {
    command: `pnpm build && pnpm exec vite preview --host 127.0.0.1 --port ${testPort}`,
    url: `http://127.0.0.1:${testPort}`,
    reuseExistingServer: true,
  },
});
