import { getCloudflareContext } from "@opennextjs/cloudflare";

// A setting or secret: from the Cloudflare Worker's environment when deployed (set with `wrangler secret put`), or
// from the root .env file when running locally. Returns undefined when it is not set, so features can switch
// themselves off until their keys exist.
export async function env(name: string): Promise<string | undefined> {
  try {
    const { env: cf } = await getCloudflareContext({ async: true });
    const value = (cf as unknown as Record<string, unknown>)[name];
    if (typeof value === "string" && value) return value;
  } catch {
    // Not running inside a Cloudflare context.
  }
  const value = process.env[name];
  return value ? value : undefined;
}

// The public address of the site, for links Stripe sends people back to.
export async function siteUrl(request?: Request): Promise<string> {
  return (await env("SITE_URL")) ?? (request ? new URL(request.url).origin : "https://pucksleuth.com");
}
