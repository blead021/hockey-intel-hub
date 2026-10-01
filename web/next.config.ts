import { existsSync } from "node:fs";
import path from "node:path";
import { initOpenNextCloudflareForDev } from "@opennextjs/cloudflare";
import type { NextConfig } from "next";

// Secrets live in one .env file at the repo root, shared with the Python pipeline.
// Values already set in the environment (CI, Cloudflare) are not overwritten.
const rootEnv = path.resolve(process.cwd(), "..", ".env");
if (existsSync(rootEnv)) process.loadEnvFile(rootEnv);

const nextConfig: NextConfig = {
  // Cloudflare image optimization is a metered service, so serve images as-is for now.
  images: { unoptimized: true },
};

export default nextConfig;

// Makes Cloudflare bindings (Hyperdrive, R2) available during `next dev`.
initOpenNextCloudflareForDev();
