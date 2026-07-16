import { SystemStatus } from "@/components/SystemStatus";

export default function Home() {
  return (
    <main className="shell">
      <section className="masthead" aria-labelledby="page-title">
        <div>
          <p className="eyebrow">MediaOS</p>
          <h1 id="page-title">Phase 0.1 Foundation</h1>
        </div>
        <span className="phase-badge">No business workflows active</span>
      </section>

      <SystemStatus />
    </main>
  );
}
