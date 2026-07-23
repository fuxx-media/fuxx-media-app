import { SystemStatus } from "@/components/SystemStatus";
import { AuthPanel } from "@/components/AuthPanel";

export default function Home() {
  return (
    <main className="shell">
      <section className="masthead" aria-labelledby="page-title">
        <div>
          <p className="eyebrow">MediaOS</p>
          <h1 id="page-title">Interne Vorgangs- und Medienbearbeitung</h1>
        </div>
        <span className="phase-badge">Echte Provider und produktive Ausführung deaktiviert</span>
      </section>

      <SystemStatus />
      <AuthPanel />
    </main>
  );
}
