import { Canvas } from "@react-three/fiber";
import { useMemo } from "react";
import { useControlStore } from "../state/controlStore";
import { useSelectionStore } from "../state/selectionStore";
import { useSimulationStore } from "../state/simStore";
import { useUiStore } from "../state/uiStore";
import { WorldScene } from "./WorldScene";

export function WorldCanvas() {
  const world = useSimulationStore((state) => state.world);
  const humanMap = useSimulationStore((state) => state.humans);
  const animalMap = useSimulationStore((state) => state.animals);
  const entityMap = useSimulationStore((state) => state.mapEntities);
  const selectedId = useSelectionStore((state) => state.selectedId);
  const selectedKind = useSelectionStore((state) => state.selectedKind);
  const clearSelection = useSelectionStore((state) => state.clearSelection);
  const viewMode = useUiStore((state) => state.viewMode);
  const adjustHumanZoom = useUiStore((state) => state.adjustHumanZoom);
  const humanZoom = useUiStore((state) => state.humanZoom);
  const claimedTargetId = useControlStore((state) => state.claimedTargetId);

  const humans = useMemo(() => Object.values(humanMap), [humanMap]);
  const animals = useMemo(() => Object.values(animalMap), [animalMap]);
  const entities = useMemo(() => Object.values(entityMap), [entityMap]);

  const claimedHuman = useMemo(
    () => humans.find((human) => human.id === claimedTargetId) ?? null,
    [claimedTargetId, humans],
  );

  if (!world) {
    return (
      <div className="world-viewport">
        <div className="world-loading">Connecting to backend world...</div>
      </div>
    );
  }

  return (
    <div
      className="world-viewport"
      onWheel={
        viewMode === "human"
          ? (event) => {
              event.preventDefault();
              adjustHumanZoom(event.deltaY > 0 ? -0.08 : 0.08);
            }
          : undefined
      }
    >
      <Canvas
        className="r3f-canvas"
        dpr={[1, 1.5]}
        gl={{ antialias: true }}
        onPointerMissed={() => clearSelection()}
        shadows
      >
        <WorldScene
          animals={animals}
          claimedHuman={claimedHuman}
          entities={entities}
          humans={humans}
          selectedId={selectedId}
          selectedKind={selectedKind}
          viewMode={viewMode}
          world={world}
          humanZoom={humanZoom}
        />
      </Canvas>
    </div>
  );
}
