import { SystemStatus } from "@/components/SystemStatus";
import { AuthPanel } from "@/components/AuthPanel";

export default function Home() {
  return (
    <main className="shell">
      <section className="masthead" aria-labelledby="page-title">
        <div>
          <p className="eyebrow">MediaOS</p>
          <h1 id="page-title">Interne Vorgangsbearbeitung</h1>
        </div>
        <span className="phase-badge">External providers disabled</span>
      </section>

      <SystemStatus />
      <AuthPanel />
    </main>
  );
}
