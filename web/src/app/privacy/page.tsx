import { PageTitle } from "@/components/ui";

export const metadata = { title: "Privacy Policy" };

// PLACEHOLDER (CLAUDE.md section 2): Brian supplies the final legal text before launch.
export default function PrivacyPage() {
  return (
    <main className="mx-auto max-w-3xl px-4 py-8">
      <PageTitle eyebrow="Legal" title="Privacy Policy" />
      <p className="mb-6 rounded-lg border-2 border-dashed border-negative bg-negative-soft p-4 text-sm font-semibold text-negative">
        Placeholder. This policy is not final and will be replaced with the official text before PuckSleuth launches
        accounts.
      </p>
      <div className="space-y-4 text-sm leading-relaxed">
        <p>Sections to be written: what we collect (account email, favorite team, subscription status; payments are
          handled by Stripe and sign-in by Clerk, which keep card and password details); how it is used; email and
          unsubscribing; cookies; who we share with (service providers only); how long we keep data; your rights and
          how to delete your account; children; changes; contact.</p>
      </div>
    </main>
  );
}
