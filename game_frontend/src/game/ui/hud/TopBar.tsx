import { useControlStore } from "../../state/controlStore";
import { useSimulationStore } from "../../state/simStore";
import { useUiStore } from "../../state/uiStore";

function networkTone(value: string) {
  if (value === "connected") {
    return "good";
  }
  if (value === "connecting" || value === "degraded") {
    return "warn";
  }
  return "bad";
}

export function TopBar() {
  const viewMode = useUiStore((state) => state.viewMode);
  const showStatusPanel = useUiStore((state) => state.showStatusPanel);
  const showInspectPanel = useUiStore((state) => state.showInspectPanel);
  const showDecreePanel = useUiStore((state) => state.showDecreePanel);
  const showEventPanel = useUiStore((state) => state.showEventPanel);
  const humanSidecarOpen = useUiStore((state) => state.humanSidecarOpen);
  const togglePanel = useUiStore((state) => state.togglePanel);
  const toggleHumanSidecar = useUiStore((state) => state.toggleHumanSidecar);
  const networkState = useSimulationStore((state) => state.networkState);
  const status = useSimulationStore((state) => state.status);
  const controlState = useControlStore((state) => state.controlState);
  const claimedTargetName = useControlStore((state) => state.claimedTargetName);

  return (
    <header className={`top-bar top-bar--${viewMode}`}>
      <div className="top-bar__title">
        <h1>Eden Chronicle</h1>
        <span>
          {viewMode === "god"
            ? "Survey the realm, shape decrees, and read the world at a glance."
            : "Walk the realm in human form. Ctrl + Shift + V toggles the right-side council."}
        </span>
      </div>
      <div className="top-bar__meta">
        <div className="top-bar__controls">
          {viewMode === "god" ? (
            <>
              <button className="chrome-toggle" data-active={showStatusPanel} onClick={() => togglePanel("status")} type="button">
                Status
              </button>
              <button className="chrome-toggle" data-active={showInspectPanel} onClick={() => togglePanel("inspect")} type="button">
                Inspector
              </button>
              <button className="chrome-toggle" data-active={showDecreePanel} onClick={() => togglePanel("decree")} type="button">
                Decrees
              </button>
              <button className="chrome-toggle" data-active={showEventPanel} onClick={() => togglePanel("events")} type="button">
                Chronicle
              </button>
            </>
          ) : (
            <button
              className="chrome-toggle"
              data-active={humanSidecarOpen}
              onClick={toggleHumanSidecar}
              type="button"
            >
              Right Council
            </button>
          )}
        </div>
        <div className="top-bar__status">
          <span className="pill" data-tone={networkTone(networkState)}>
            Network: {networkState}
          </span>
          <span className="pill">Mode: {viewMode}</span>
          <span className="pill">Control: {controlState}</span>
          {claimedTargetName ? <span className="pill">Avatar: {claimedTargetName}</span> : null}
          <span className="pill">Tick: {status?.tick ?? "--"}</span>
          <span className="pill">Pop: {status?.pop ?? "--"}</span>
        </div>
      </div>
    </header>
  );
}
