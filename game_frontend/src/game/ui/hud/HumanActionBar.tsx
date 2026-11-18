import { useMemo, useState } from "react";
import { sendControlEvent } from "../../protocol/api";
import { useControlStore } from "../../state/controlStore";
import { useSelectionStore } from "../../state/selectionStore";
import { useSimulationStore } from "../../state/simStore";

export function HumanActionBar() {
  const claimedTargetId = useControlStore((state) => state.claimedTargetId);
  const selectedId = useSelectionStore((state) => state.selectedId);
  const selectedKind = useSelectionStore((state) => state.selectedKind);
  const humans = useSimulationStore((state) => state.humans);
  const animals = useSimulationStore((state) => state.animals);
  const entities = useSimulationStore((state) => state.mapEntities);
  const [message, setMessage] = useState<string | null>(null);

  const selectedTargetName = useMemo(() => {
    if (!selectedId || !selectedKind) {
      return null;
    }
    if (selectedKind === "human") {
      return humans[selectedId]?.name ?? selectedId;
    }
    if (selectedKind === "animal") {
      return animals[selectedId]?.name ?? selectedId;
    }
    return entities[selectedId]?.name ?? selectedId;
  }, [animals, entities, humans, selectedId, selectedKind]);

  if (!claimedTargetId) {
    return null;
  }

  const activeClaimedTargetId = claimedTargetId;

  async function submitAction(action: "attack" | "talk" | "interact", text?: string) {
    try {
      await sendControlEvent({
        action,
        controlledTargetId: activeClaimedTargetId,
        selectedTargetId: selectedId,
        selectedTargetKind: selectedKind,
        selectedTargetName,
        text,
      });
      setMessage(`${action} sent${selectedTargetName ? ` to ${selectedTargetName}` : ""}.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : `${action} failed`);
    }
  }

  return (
    <div className="human-action-bar human-action-bar--overlay">
      <div className="human-action-bar__buttons">
        <button className="action-button" onClick={() => void submitAction("attack")} type="button">
          Attack
        </button>
        <button
          className="action-button"
          onClick={() => {
            const text = window.prompt("What should the controlled human say?");
            if (text && text.trim()) {
              void submitAction("talk", text.trim());
            }
          }}
          type="button"
        >
          Talk
        </button>
        <button className="action-button" onClick={() => void submitAction("interact")} type="button">
          Interact
        </button>
      </div>
      <div className="human-action-bar__meta">
        <span>WASD follows the camera</span>
        <span>Shift sprint</span>
        <span>{selectedTargetName ? `Target: ${selectedTargetName}` : "Select a target for actions"}</span>
        {message ? <span>{message}</span> : null}
      </div>
    </div>
  );
}
