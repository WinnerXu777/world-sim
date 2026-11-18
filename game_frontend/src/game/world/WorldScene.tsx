import {
  Billboard,
  Grid,
  Html,
  OrbitControls,
  PerspectiveCamera,
  Sky,
  useTexture,
} from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import { Suspense, useMemo, useRef } from "react";
import type { RefObject } from "react";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import * as THREE from "three";
import type { ActorView, MapEntityView, ViewMode, WorldInfo } from "../protocol/types";
import { useSelectionStore } from "../state/selectionStore";
import { sceneAssets } from "./sceneAssets";
import { HUMAN_CAMERA_OFFSET, humanCameraHeight, humanZoomDistanceScale } from "./humanView";
import { ModelEntity } from "./ModelEntity";

interface WorldSceneProps {
  animals: ActorView[];
  claimedHuman: ActorView | null;
  entities: MapEntityView[];
  humanZoom: number;
  humans: ActorView[];
  selectedId: string | null;
  selectedKind: "human" | "animal" | "entity" | null;
  viewMode: ViewMode;
  world: WorldInfo;
}

function markerBaseSize(world: WorldInfo) {
  return Math.max(10, Math.round(Math.max(world.width, world.height) * 0.012));
}

function useCameraRig(
  viewMode: ViewMode,
  world: WorldInfo,
  claimedHuman: ActorView | null,
  humanZoom: number,
  controlsRef: RefObject<OrbitControlsImpl | null>,
) {
  const desiredPosition = useRef(new THREE.Vector3());
  const desiredLookAt = useRef(new THREE.Vector3());
  const smoothedLookAt = useRef(new THREE.Vector3());
  const previousMode = useRef<ViewMode>(viewMode);
  const initializedGodCamera = useRef(false);

  useFrame(({ camera }, delta) => {
    const modeChanged = previousMode.current !== viewMode;
    previousMode.current = viewMode;

    if (viewMode === "human" && claimedHuman) {
      const distanceScale = humanZoomDistanceScale(humanZoom);
      desiredPosition.current.set(
        claimedHuman.x + HUMAN_CAMERA_OFFSET.x * distanceScale,
        humanCameraHeight(world) * (0.9 + (1 - humanZoom) * 0.85),
        claimedHuman.y + HUMAN_CAMERA_OFFSET.y * distanceScale,
      );
      desiredLookAt.current.set(claimedHuman.x, 0, claimedHuman.y);

      camera.position.lerp(desiredPosition.current, 1 - Math.pow(0.002, delta));
      smoothedLookAt.current.lerp(desiredLookAt.current, 1 - Math.pow(0.001, delta));
      camera.lookAt(smoothedLookAt.current);

      if (controlsRef.current) {
        controlsRef.current.target.copy(smoothedLookAt.current);
        controlsRef.current.update();
      }
      return;
    }

    if (!controlsRef.current) {
      return;
    }

    desiredPosition.current.set(
      world.width * 0.5,
      Math.max(world.width, world.height) * 0.72,
      world.height * 0.82,
    );
    desiredLookAt.current.set(world.width * 0.5, 0, world.height * 0.5);

    if (modeChanged || !initializedGodCamera.current) {
      smoothedLookAt.current.copy(desiredLookAt.current);
      camera.position.copy(desiredPosition.current);
      controlsRef.current.target.copy(desiredLookAt.current);
      camera.lookAt(desiredLookAt.current);
      controlsRef.current.update();
      initializedGodCamera.current = true;
    }
  }, 0);
}

function Ground({ world }: { world: WorldInfo }) {
  const groundTexture = useTexture(sceneAssets.groundTextureUrl);

  groundTexture.wrapS = THREE.RepeatWrapping;
  groundTexture.wrapT = THREE.RepeatWrapping;
  groundTexture.repeat.set(Math.max(4, world.width / 192), Math.max(4, world.height / 192));
  groundTexture.magFilter = THREE.NearestFilter;
  groundTexture.minFilter = THREE.NearestFilter;

  return (
    <group position={[world.width * 0.5, 0, world.height * 0.5]}>
      <mesh receiveShadow rotation-x={-Math.PI / 2}>
        <planeGeometry args={[world.width, world.height]} />
        <meshStandardMaterial color="#6c5b3a" map={groundTexture} roughness={1} />
      </mesh>
      <Grid
        args={[world.width, world.height]}
        cellColor="#8c6d34"
        cellSize={40}
        fadeDistance={world.width + world.height}
        fadeStrength={0.55}
        infiniteGrid={false}
        sectionColor="#d8b661"
        sectionSize={200}
      />
    </group>
  );
}

function SelectionRing({
  color,
  radius,
  position,
  visible,
}: {
  color: string;
  radius: number;
  position: [number, number, number];
  visible: boolean;
}) {
  if (!visible) {
    return null;
  }

  return (
    <mesh position={position} rotation-x={-Math.PI / 2}>
      <ringGeometry args={[radius * 0.82, radius, 32]} />
      <meshBasicMaterial color={color} side={THREE.DoubleSide} transparent opacity={0.95} />
    </mesh>
  );
}

function ActorMarker({
  actor,
  color,
  kind,
  size,
  spriteUrl,
  selected,
  controlled,
}: {
  actor: ActorView;
  color: string;
  kind: "human" | "animal";
  size: number;
  spriteUrl: string;
  selected: boolean;
  controlled: boolean;
}) {
  const setSelection = useSelectionStore((state) => state.setSelection);
  const spriteTexture = useTexture(spriteUrl);

  spriteTexture.magFilter = THREE.NearestFilter;
  spriteTexture.minFilter = THREE.NearestFilter;

  return (
    <group position={[actor.x, 0, actor.y]}>
      <SelectionRing
        color={controlled ? "#88c8ff" : "#6fd5b3"}
        position={[0, 0.1, 0]}
        radius={size * 0.72}
        visible={selected || controlled}
      />
      <group
        onClick={(event) => {
          event.stopPropagation();
          setSelection(kind, actor.id);
        }}
        position={[0, kind === "human" ? size * 0.88 : size * 0.78, 0]}
      >
        <Billboard follow lockX={false} lockY={false} lockZ={false}>
          <mesh castShadow>
            <planeGeometry args={[size * (kind === "human" ? 1.3 : 1.45), size * (kind === "human" ? 1.65 : 1.8)]} />
            <meshStandardMaterial
              alphaTest={0.2}
              color={color}
              map={spriteTexture}
              roughness={0.92}
              transparent
            />
          </mesh>
        </Billboard>
      </group>
      {(selected || controlled) && (actor.name || actor.id) ? (
        <Billboard position={[0, size * 1.8, 0]} follow>
          <Html center distanceFactor={18}>
            <div className="world-label world-label--floating">{actor.name ?? actor.id}</div>
          </Html>
        </Billboard>
      ) : null}
    </group>
  );
}

/** Water plane for lake / sea entities */
function WaterPlane({
  entity,
  baseSize,
}: {
  entity: MapEntityView;
  baseSize: number;
}) {
  const radius = (entity.radius ?? baseSize) * 0.9;
  const isLake = entity.typeLabel === "lake";

  return (
    <mesh
      position={[entity.x, isLake ? 0.3 : -0.1, entity.y]}
      rotation-x={-Math.PI / 2}
      receiveShadow
    >
      <circleGeometry args={[radius, 32]} />
      <meshStandardMaterial
        color={isLake ? "#3d7ea6" : "#1a4a6b"}
        roughness={0.2}
        metalness={0.1}
        transparent
        opacity={0.85}
      />
    </mesh>
  );
}

export function WorldScene({
  animals,
  claimedHuman,
  entities,
  humanZoom,
  humans,
  selectedId,
  selectedKind,
  viewMode,
  world,
}: WorldSceneProps) {
  const controlsRef = useRef<OrbitControlsImpl | null>(null);

  useCameraRig(viewMode, world, claimedHuman, humanZoom, controlsRef);
  const baseSize = markerBaseSize(world);

  const sceneFog = useMemo(
    () => new THREE.Fog("#b8cfe0", Math.max(world.width, world.height) * 0.5, Math.max(world.width, world.height) * 1.6),
    [world.height, world.width],
  );

  return (
    <>
      <color args={["#87ceeb"]} attach="background" />
      <primitive attach="fog" object={sceneFog} />
      <Sky sunPosition={[100, 60, 80]} turbidity={4} rayleigh={0.5} />
      <PerspectiveCamera
        makeDefault
        far={Math.max(world.width, world.height) * 4}
        fov={viewMode === "human" ? 48 : 30}
        near={0.1}
        position={[world.width * 0.5, Math.max(world.width, world.height) * 0.72, world.height * 0.82]}
      />
      <OrbitControls
        ref={controlsRef}
        enablePan={viewMode === "god"}
        enableRotate={false}
        enableZoom
        enabled={viewMode === "god"}
        maxDistance={Math.max(world.width, world.height) * 1.4}
        minDistance={18}
        zoomSpeed={0.85}
      />
      <ambientLight intensity={0.6} color="#c8d4e8" />
      <hemisphereLight args={["#87ceeb", "#556b2f", 0.4]} />
      <directionalLight
        castShadow
        intensity={1.6}
        position={[world.width * 0.3, Math.max(world.width, world.height) * 0.45, world.height * 0.2]}
        shadow-mapSize-height={2048}
        shadow-mapSize-width={2048}
        color="#fff5e0"
      />
      <Ground world={world} />
      {/* Water planes for lake entities only (sea is background) */}
      {entities
        .filter((e) => e.typeLabel === "lake")
        .map((entity) => (
          <WaterPlane key={`water-${entity.id}`} entity={entity} baseSize={baseSize} />
        ))}

      {/* 3D model entities */}
      {entities
        .filter((e) => e.typeLabel !== "sea")
        .map((entity) => (
          <Suspense key={entity.id} fallback={null}>
            <ModelEntity
              entity={entity}
              baseSize={baseSize}
              selected={selectedId === entity.id && selectedKind === "entity"}
            />
          </Suspense>
        ))}
      {animals.map((animal) => (
        <ActorMarker
          actor={animal}
          color="#f1d4b1"
          controlled={false}
          key={animal.id}
          kind="animal"
          size={baseSize * 0.95}
          spriteUrl={sceneAssets.animalSpriteUrl}
          selected={selectedId === animal.id && selectedKind === "animal"}
        />
      ))}
      {humans.map((human) => (
        <ActorMarker
          actor={human}
          color="#dce6d3"
          controlled={claimedHuman?.id === human.id}
          key={human.id}
          kind="human"
          size={baseSize}
          spriteUrl={sceneAssets.humanSpriteUrl}
          selected={selectedId === human.id && selectedKind === "human"}
        />
      ))}
    </>
  );
}
