import { useState } from "react";
import { useHumanControlLoop } from "../controls/useHumanControlLoop";
import { useControlStore } from "../state/controlStore";
import { useSimulationStore } from "../state/simStore";
import { useUiStore } from "../state/uiStore";
import { HumanActionBar } from "../ui/hud/HumanActionBar";
import { ModeTabs } from "../ui/hud/ModeTabs";
import { WorldCanvas } from "./WorldCanvas";

export function WorldScreen() {
  useHumanControlLoop();

  const viewMode = useUiStore((state) => state.viewMode);
  const setViewMode = useUiStore((state) => state.setViewMode);
  const humanSidecarOpen = useUiStore((state) => state.humanSidecarOpen);
  const releaseTarget = useControlStore((state) => state.releaseTarget);
  const enterHumanMode = useControlStore((state) => state.enterHumanMode);
  const claimedTargetId = useControlStore((state) => state.claimedTargetId);
  const claimedTargetName = useControlStore((state) => state.claimedTargetName);
  const lastFrameId = useSimulationStore((state) => state.lastFrameId);
  const world = useSimulationStore((state) => state.world);
  const [isEntryDialogOpen, setIsEntryDialogOpen] = useState(false);
  const [pendingName, setPendingName] = useState("");

  async function handleHumanModeEntry(preferredName?: string) {
    if (claimedTargetId) {
      setViewMode("human");
      return;
    }

    const result = await enterHumanMode(preferredName);
    if (result === "needs_name") {
      setIsEntryDialogOpen(true);
      return;
    }
    if (result === "entered") {
      setIsEntryDialogOpen(false);
      if (preferredName) {
        setPendingName(preferredName);
      }
    }
  }

  if (viewMode === "human") {
    return (
      <main className="panel world-panel world-panel--human">
        <WorldCanvas />
        <div className="human-hud">
          <div className="human-hud__top">
            <div className="human-hud__cluster human-hud__cluster--left">
              <ModeTabs
                mode={viewMode}
                onSelect={(mode) => {
                  if (mode === "god") {
                    void releaseTarget();
                    return;
                  }
                  void handleHumanModeEntry();
                }}
              />
            </div>
            <div className="human-hud__cluster human-hud__cluster--right">
              <button className="action-button" onClick={() => void releaseTarget()} type="button">
                Leave Human Form
              </button>
              {claimedTargetName ? <span className="pill">Avatar: {claimedTargetName}</span> : null}
              <span className="pill" data-tone={humanSidecarOpen ? "good" : "warn"}>
                Sidecar: {humanSidecarOpen ? "open" : "hidden"}
              </span>
              <span className="pill">Frame: {lastFrameId ?? "--"}</span>
            </div>
          </div>
          <HumanActionBar />
        </div>
        {isEntryDialogOpen ? (
          <div className="enter-world-dialog-backdrop">
            <div className="enter-world-dialog">
              <div className="panel__header">
                <h3>Enter World</h3>
              </div>
              <div className="panel__body stack">
                <label className="stack">
                  <span className="selection-item__meta">Name</span>
                  <input
                    className="dialog-input"
                    onChange={(event) => setPendingName(event.target.value)}
                    placeholder="Choose your human name"
                    type="text"
                    value={pendingName}
                  />
                </label>
                <div className="row">
                  <button
                    className="action-button"
                    data-variant="primary"
                    disabled={pendingName.trim().length === 0}
                    onClick={() => void handleHumanModeEntry(pendingName.trim())}
                    type="button"
                  >
                    Enter Human Mode
                  </button>
                  <button
                    className="tool-button"
                    onClick={() => setIsEntryDialogOpen(false)}
                    type="button"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            </div>
          </div>
        ) : null}
      </main>
    );
  }

  return (
    <main className="panel world-panel world-panel--god">
      <div className="world-toolbar">
        <div className="world-toolbar__group">
          <ModeTabs
            mode={viewMode}
            onSelect={(mode) => {
              if (mode === "god") {
                void releaseTarget();
                return;
              }
              void handleHumanModeEntry();
            }}
          />
        </div>
        <div className="world-toolbar__group">
          {claimedTargetName ? <span className="pill">Avatar: {claimedTargetName}</span> : null}
        </div>
      </div>
      {isEntryDialogOpen ? (
        <div className="enter-world-dialog-backdrop">
          <div className="enter-world-dialog">
            <div className="panel__header">
              <h3>Enter World</h3>
            </div>
            <div className="panel__body stack">
              <label className="stack">
                <span className="selection-item__meta">Name</span>
                <input
                  className="dialog-input"
                  onChange={(event) => setPendingName(event.target.value)}
                  placeholder="Choose your human name"
                  type="text"
                  value={pendingName}
                />
              </label>
              <div className="row">
                <button
                  className="action-button"
                  data-variant="primary"
                  disabled={pendingName.trim().length === 0}
                  onClick={() => void handleHumanModeEntry(pendingName.trim())}
                  type="button"
                >
                  Enter Human Mode
                </button>
                <button
                  className="tool-button"
                  onClick={() => setIsEntryDialogOpen(false)}
                  type="button"
                >
                  Cancel
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}
      <WorldCanvas />
      <div className="world-footer">
        <span>
          World: {world ? `${world.width} x ${world.height}` : "--"} - Frame {lastFrameId ?? "--"}
        </span>
        <span>
          {viewMode === "god"
            ? "Hide or reveal panels from the top bar to give the map more room."
            : "WASD follows the camera angle. Ctrl + Shift + V reveals the right-side council."}
        </span>
      </div>
    </main>
  );
}
