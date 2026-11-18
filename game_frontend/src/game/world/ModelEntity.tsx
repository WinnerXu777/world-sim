/**
 * ModelEntity.tsx
 * ===============
 * Renders a 3D glTF model for a map entity, replacing the old cylinder
 * placeholder. Uses drei's useGLTF for loading and supports:
 * - variant selection via entity ID hash
 * - deterministic random rotation
 * - scale from backend radius + asset config
 * - click selection
 * - hover labels
 */

import { Billboard, Html, useGLTF } from "@react-three/drei";
import { useMemo, useRef } from "react";
import * as THREE from "three";
import type { MapEntityView } from "../protocol/types";
import { useSelectionStore } from "../state/selectionStore";
import { resolveAsset, entityRotation } from "./assetRegistry";

// ---------------------------------------------------------------------------
// Fallback marker — shown while model loads or for unknown types
// ---------------------------------------------------------------------------

function FallbackMarker({
  entity,
  size,
  selected,
}: {
  entity: MapEntityView;
  size: number;
  selected: boolean;
}) {
  const setSelection = useSelectionStore((state) => state.setSelection);

  return (
    <group position={[entity.x, 0, entity.y]}>
      {selected && (
        <mesh rotation-x={-Math.PI / 2} position={[0, 0.08, 0]}>
          <ringGeometry args={[size * 0.78, size, 32]} />
          <meshBasicMaterial
            color="#b5c97d"
            side={THREE.DoubleSide}
            transparent
            opacity={0.95}
          />
        </mesh>
      )}
      <mesh
        castShadow
        onClick={(event) => {
          event.stopPropagation();
          setSelection("entity", entity.id);
        }}
        position={[0, size * 0.45, 0]}
      >
        <cylinderGeometry args={[size * 0.52, size * 0.68, size * 0.9, 10]} />
        <meshStandardMaterial color="#95a86e" roughness={0.9} />
      </mesh>
      {selected && (entity.name || entity.id) ? (
        <Billboard position={[0, size * 1.55, 0]} follow>
          <Html center distanceFactor={18}>
            <div className="world-label world-label--floating">
              {entity.name ?? entity.id}
            </div>
          </Html>
        </Billboard>
      ) : null}
    </group>
  );
}

// ---------------------------------------------------------------------------
// Loaded 3D model
// ---------------------------------------------------------------------------

function LoadedModel({
  entity,
  modelPath,
  modelScale,
  rotationY,
  entityScale,
  selected,
}: {
  entity: MapEntityView;
  modelPath: string;
  modelScale: number;
  rotationY: number;
  entityScale: number;
  selected: boolean;
}) {
  const { scene } = useGLTF(modelPath);
  const setSelection = useSelectionStore((state) => state.setSelection);
  const groupRef = useRef<THREE.Group>(null);

  const clonedScene = useMemo(() => {
    const clone = scene.clone(true);
    clone.traverse((child) => {
      if ((child as THREE.Mesh).isMesh) {
        const mesh = child as THREE.Mesh;
        mesh.castShadow = true;
        mesh.receiveShadow = true;
      }
    });
    return clone;
  }, [scene]);

  // Compute bounding box for selection ring sizing
  const bbox = useMemo(() => {
    const box = new THREE.Box3().setFromObject(clonedScene);
    return box;
  }, [clonedScene]);

  const combinedScale = modelScale * entityScale;
  const bboxSize = new THREE.Vector3();
  bbox.getSize(bboxSize);
  const ringRadius = Math.max(bboxSize.x, bboxSize.z) * combinedScale * 0.5;
  const modelHeight = bboxSize.y * combinedScale;

  return (
    <group position={[entity.x, 0, entity.y]} ref={groupRef}>
      {/* Selection ring */}
      {selected && (
        <mesh rotation-x={-Math.PI / 2} position={[0, 0.15, 0]}>
          <ringGeometry args={[ringRadius * 0.85, ringRadius * 1.05, 32]} />
          <meshBasicMaterial
            color="#b5c97d"
            side={THREE.DoubleSide}
            transparent
            opacity={0.9}
          />
        </mesh>
      )}

      {/* The actual 3D model */}
      <group
        rotation-y={rotationY}
        scale={[combinedScale, combinedScale, combinedScale]}
        onClick={(event) => {
          event.stopPropagation();
          setSelection("entity", entity.id);
        }}
      >
        <primitive object={clonedScene} />
      </group>

      {/* Floating label on selection */}
      {selected && (entity.name || entity.id) ? (
        <Billboard position={[0, modelHeight + 2, 0]} follow>
          <Html center distanceFactor={18}>
            <div className="world-label world-label--floating">
              {entity.name ?? entity.id}
            </div>
          </Html>
        </Billboard>
      ) : null}
    </group>
  );
}

// ---------------------------------------------------------------------------
// Main export — decides between loaded model and fallback
// ---------------------------------------------------------------------------

interface ModelEntityProps {
  entity: MapEntityView;
  baseSize: number;
  selected: boolean;
}

export function ModelEntity({ entity, baseSize, selected }: ModelEntityProps) {
  const asset = resolveAsset(entity.typeLabel, entity.id);

  if (!asset) {
    return (
      <FallbackMarker
        entity={entity}
        size={Math.min(
          Math.max((entity.radius ?? baseSize) * 0.08, baseSize * 0.8),
          baseSize * 2.4,
        )}
        selected={selected}
      />
    );
  }

  // Scale factor from entity radius.
  // Backend entity.radius is in world-px (typically 40–150 for natural features,
  // 8–25 for structures). Models are ~1–7 native units tall/wide.
  // We want the rendered model to fill roughly entity.radius in world space.
  const entityRadius = entity.radius ?? baseSize;
  const entityScale = Math.max(1, entityRadius * 0.12);
  const rotY = asset.randomRotateY ? entityRotation(entity.id) : (asset.rotationY ?? 0);

  return (
    <LoadedModel
      entity={entity}
      entityScale={entityScale}
      modelPath={asset.path}
      modelScale={asset.scale}
      rotationY={rotY}
      selected={selected}
    />
  );
}
