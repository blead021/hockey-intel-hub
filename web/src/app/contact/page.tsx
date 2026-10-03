import { connection } from "next/server";
import { PageTitle } from "@/components/ui";
import { env } from "@/lib/env";

export const metadata = { title: "Contact" };

// Contact (CLAUDE.md section 2). The address comes from CONTACT_EMAIL, so no personal address is published until
// Brian sets one up.
export default async function ContactPage() {
  await connection();
  const email = await env("CONTACT_EMAIL");
  return (
    <main className="mx-auto max-w-3xl px-4 py-8">
      <PageTitle eyebrow="Get in touch" title="Contact" />
      <div className="rounded-lg border border-border bg-surface p-5 text-sm leading-relaxed">
        <p>Questions, corrections, or ideas for PuckSleuth? We read everything.</p>
        {email ? (
          <p className="mt-3">Email <a href={`mailto:${email}`} className="font-semibold underline">{email}</a></p>
        ) : (
          <p className="mt-3 text-muted">A contact address is coming soon.</p>
        )}
        <p className="mt-3 text-muted">Spotted a wrong contract or cap number? Tell us the player and where you saw the correct figure.</p>
      </div>
    </main>
  );
}
