import { defineCloudflareConfig } from "@opennextjs/cloudflare";

// No incremental cache yet. Add the R2 incremental cache when pages start
// using time-based revalidation. See https://opennext.js.org/cloudflare/caching
export default defineCloudflareConfig({});
