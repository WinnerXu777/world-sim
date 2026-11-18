import { useSimulationStore } from "../../state/simStore";

export function StatusPanel() {
  const status = useSimulationStore((state) => state.status);
  const world = useSimulationStore((state) => state.world);
  const errorMessage = useSimulationStore((state) => state.errorMessage);
  const humans = useSimulationStore((state) => Object.keys(state.humans).length);
  const animals = useSimulationStore((state) => Object.keys(state.animals).length);

  return (
    <section className="panel">
      <div className="panel__header">
        <h2>Status</h2>
      </div>
      <div className="panel__body stack">
        <div className="metric-grid">
          <div className="metric">
            <span className="metric__label">Protocol</span>
            <span className="metric__value">{status?.protocol ?? "--"}</span>
          </div>
          <div className="metric">
            <span className="metric__label">Map</span>
            <span className="metric__value">{status?.mapName ?? "--"}</span>
          </div>
          <div className="metric">
            <span className="metric__label">Humans</span>
            <span className="metric__value">{humans}</span>
          </div>
          <div className="metric">
            <span className="metric__label">Animals</span>
            <span className="metric__value">{animals}</span>
          </div>
          <div className="metric">
            <span className="metric__label">World Width</span>
            <span className="metric__value">{world?.width ?? "--"}</span>
          </div>
          <div className="metric">
            <span className="metric__label">World Height</span>
            <span className="metric__value">{world?.height ?? "--"}</span>
          </div>
        </div>
        {errorMessage ? <div className="pill" data-tone="bad">{errorMessage}</div> : null}
      </div>
    </section>
  );
}
