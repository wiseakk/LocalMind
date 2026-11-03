import { defineConfig } from '@playwright/test';
export default defineConfig({testDir:'./tests/browser',
  // Decorative scene is excluded from user mode. Retain its legacy browser
  // component suite explicitly; DOM component regressions still run by default.
  testIgnore:process.env.LOCALMIND_LEGACY_SCENE_TESTS==='1'?[]:['**/constellation.spec.mjs','**/canvas-performance.spec.mjs'],fullyParallel:false,workers:1,timeout:30000,
  use:{baseURL:process.env.LOCALMIND_TEST_URL || 'http://127.0.0.1:8765',viewport:{width:1440,height:1000},headless:true},
  reporter:'list',outputDir:'test-results'});
