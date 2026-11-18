import { useMemo } from "react";
import { useSelectionStore } from "../../state/selectionStore";
import { useSimulationStore } from "../../state/simStore";

export function InspectPanel() {
  const selectedId = useSelectionStore((state) => state.selectedId);
  const selectedKind = useSelectionStore((state) => state.selectedKind);
  const setSelection = useSelectionStore((state) => state.setSelection);
  const clearSelection = useSelectionStore((state) => state.clearSelection);
  const humanMap = useSimulationStore((state) => state.humans);
  const animalMap = useSimulationStore((state) => state.animals);
  const entityMap = useSimulationStore((state) => state.mapEntities);

  const humans = useMemo(() => Object.values(humanMap), [humanMap]);
  const animals = useMemo(() => Object.values(animalMap), [animalMap]);
  const entities = useMemo(() => Object.values(entityMap), [entityMap]);

  const selected = useMemo(() => {
    if (!selectedId || !selectedKind) {
      return null;
    }
    if (selectedKind === "human") {
      return humans.find((item) => item.id === selectedId) ?? null;
    }
    if (selectedKind === "animal") {
      return animals.find((item) => item.id === selectedId) ?? null;
    }
    return entities.find((item) => item.id === selectedId) ?? null;
  }, [animals, entities, humans, selectedId, selectedKind]);

  return (
    <section className="panel">
      <div className="panel__header">
        <h2>Inspector</h2>
        <button className="tool-button" onClick={clearSelection} type="button">
          Clear
        </button>
      </div>
      <div className="panel__body stack">
        {selected ? (
          <>
            <div className="selection-item" data-active="true">
              <strong>{selected.name ?? selected.id}</strong>
              <div className="selection-item__meta">
                {selectedKind} at ({Math.round(selected.x)}, {Math.round(selected.y)})
              </div>
              {"action" in selected && selected.action ? (
                <div className="selection-item__meta">Action: {selected.action}</div>
              ) : null}
              {"playerAvatar" in selected && selected.playerAvatar ? (
                <div className="selection-item__meta">Player avatar</div>
              ) : null}
            </div>
          </>
        ) : (
          <div className="empty-state">Select a human, animal, or map entity to inspect it.</div>
        )}
        <div className="stack">
          <div className="selection-item__meta">Humans</div>
          <div className="selection-list">
            {humans.slice(0, 8).map((human) => (
              <button
                key={human.id}
                className="selection-item"
                data-active={selectedId === human.id}
                onClick={() => setSelection("human", human.id)}
                type="button"
              >
                <strong>{human.name ?? human.id}</strong>
                <div className="selection-item__meta">
                  ({Math.round(human.x)}, {Math.round(human.y)})
                </div>
                {human.playerAvatar ? <div className="selection-item__meta">Player avatar</div> : null}
              </button>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
