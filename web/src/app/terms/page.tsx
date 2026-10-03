import { PageTitle } from "@/components/ui";

export const metadata = { title: "Terms of Service" };

// PLACEHOLDER (CLAUDE.md section 2): Brian supplies the final legal text before launch.
export default function TermsPage() {
  return (
    <main className="mx-auto max-w-3xl px-4 py-8">
      <PageTitle eyebrow="Legal" title="Terms of Service" />
      <p className="mb-6 rounded-lg border-2 border-dashed border-negative bg-negative-soft p-4 text-sm font-semibold text-negative">
        Placeholder. These terms are not final and will be replaced with the official text before PuckSleuth launches
        paid subscriptions.
      </p>
      <div className="space-y-4 text-sm leading-relaxed">
        <p>Sections to be written: who can use PuckSleuth; accounts; subscriptions, renewals, and cancellation; refunds;
          acceptable use; the data shown (estimates and opinions, not guarantees; not betting or financial advice);
          intellectual property; third-party sources and links; limitation of liability; changes to these terms;
          governing law; contact.</p>
      </div>
    </main>
  );
}
