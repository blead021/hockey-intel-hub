import { getCloudflareContext } from "@opennextjs/cloudflare";
import postgres from "postgres";

// On Cloudflare, connect through the Hyperdrive binding, which pools connections.
// Outside a Cloudflare context, fall back to DATABASE_URL from the root .env file.
async function connectionString(): Promise<string> {
  try {
    const { env } = await getCloudflareContext({ async: true });
    if (env.HYPERDRIVE?.connectionString) return env.HYPERDRIVE.connectionString;
  } catch {
    // Not running inside a Cloudflare context.
  }
  const url = process.env.DATABASE_URL;
  if (!url) throw new Error("DATABASE_URL is not set. Copy .env.example to .env at the repo root.");
  return url;
}

// Runs one query on a fresh connection. Workers cannot reuse connections across
// requests, and Hyperdrive makes opening a new one cheap.
export async function query<T extends Record<string, unknown>>(text: string, params: postgres.ParameterOrJSON<never>[] = []): Promise<T[]> {
  // fetch_types off: skips an extra round trip that Hyperdrive does not need.
  const sql = postgres(await connectionString(), { max: 1, fetch_types: false });
  try {
    return (await sql.unsafe<T[]>(text, params)) as T[];
  } finally {
    await sql.end();
  }
}
