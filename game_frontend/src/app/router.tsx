import { useEffect } from "react";
import { DecreePanel } from "../game/ui/panels/DecreePanel";
import { EventFeedPanel } from "../game/ui/panels/EventFeedPanel";
import { InspectPanel } from "../game/ui/panels/InspectPanel";
import { StatusPanel } from "../game/ui/panels/StatusPanel";
import { TopBar } from "../game/ui/hud/TopBar";
import { useUiStore } from "../game/state/uiStore";
import { WorldScreen } from "../game/world/WorldScreen";

function isTextInputTarget(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) {
    return false;
  }

  const tag = target.tagName.toLowerCase();
  return tag === "input" || tag === "textarea" || target.isContentEditable;
}

export function AppRouter() {
  const viewMode = useUiStore((state) => state.viewMode);
  const showStatusPanel = useUiStore((state) => state.showStatusPanel);
  const showInspectPanel = useUiStore((state) => state.showInspectPanel);
  const showDecreePanel = useUiStore((state) => state.showDecreePanel);
  const showEventPanel = useUiStore((state) => state.showEventPanel);
  const humanSidecarOpen = useUiStore((state) => state.humanSidecarOpen);
  const toggleHumanSidecar = useUiStore((state) => state.toggleHumanSidecar);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (isTextInputTarget(event.target)) {
        return;
      }
      if (viewMode === "human" && event.ctrlKey && event.shiftKey && event.code === "KeyV") {
        event.preventDefault();
        toggleHumanSidecar();
      }
    }

    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [toggleHumanSidecar, viewMode]);

  const showLeftRail = viewMode === "god" && (showStatusPanel || showInspectPanel);
  const showRightRail = viewMode === "god" && (showDecreePanel || showEventPanel);

  return (
    <div className={`app-shell app-shell--${viewMode}`}>
      <TopBar />
      {viewMode === "god" ? (
        <>
          {showLeftRail ? (
            <aside className="sidebar">
              {showStatusPanel ? <StatusPanel /> : null}
              {showInspectPanel ? <InspectPanel /> : null}
            </aside>
          ) : null}
          <WorldScreen />
          {showRightRail ? (
            <section className="panel-stack">
              {showDecreePanel ? <DecreePanel /> : null}
              {showEventPanel ? <EventFeedPanel /> : null}
            </section>
          ) : null}
        </>
      ) : (
        <section className="human-stage">
          <WorldScreen />
          {humanSidecarOpen ? (
            <aside className="human-sidecar">
              <div className="human-sidecar__inner">
                <StatusPanel />
                <InspectPanel />
                <DecreePanel />
                <EventFeedPanel />
              </div>
            </aside>
          ) : null}
        </section>
      )}
    </div>
  );
}
