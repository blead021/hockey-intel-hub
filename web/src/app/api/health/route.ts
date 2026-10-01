import { connection } from "next/server";
import { query } from "@/lib/db";

// Confirms the app can reach the database. Lists data source switches, no secrets.
export async function GET() {
  await connection();
  try {
    const sources = await query<{ key: string; enabled: boolean }>(
      "select key, enabled from data_sources order by key",
    );
    return Response.json({ ok: true, database: "connected", data_sources: sources });
  } catch (error) {
    console.error("health check failed", error);
    return Response.json({ ok: false, database: "unreachable" }, { status: 503 });
  }
}
