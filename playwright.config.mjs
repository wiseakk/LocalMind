import { defineConfig } from '@playwright/test';
export default defineConfig({testDir:'./tests/browser',fullyParallel:false,workers:1,timeout:30000,
  use:{baseURL:process.env.LOCALMIND_TEST_URL || 'http://127.0.0.1:8765',viewport:{width:1440,height:1000},headless:true},
  reporter:'list',outputDir:'test-results'});
