export type ViewMode = "god" | "human";

export type NetworkState =
  | "connecting"
  | "connected"
  | "degraded"
  | "disconnected"
  | "error";

export interface WorldInfo {
  width: number;
  height: number;
  agent_frame_hz: number;
  map_delta_hz: number;
}

export interface MapEntityView {
  id: string;
  name?: string;
  type?: string;
  typeLabel?: string;
  x: number;
  y: number;
  radius?: number;
  shapeKind?: string;
}

export interface ActorView {
  id: string;
  name?: string;
  kind: "human" | "animal";
  x: number;
  y: number;
  hp?: number;
  maxHp?: number;
  action?: string;
  locomotion?: string;
  controlled?: boolean;
  playerAvatar?: boolean;
  controllerId?: string | null;
  controlMode?: string | null;
}

export interface ControlSessionView {
  controllerId: string;
  targetId: string;
  targetKind: string;
  targetName?: string;
  mode?: string;
}

export interface ControlActionResult {
  ok: boolean;
  reason?: string;
  requiresName?: boolean;
  controllerId?: string;
  targetId?: string;
  targetKind?: string;
  targetName?: string;
  mode?: string;
  spawned?: boolean;
  incarnation?: string;
}

export interface EventView {
  id: string;
  text: string;
  tick?: number;
  category?: string;
}

export interface BootstrapPayload {
  world: WorldInfo;
  map: {
    entities: MapEntityView[];
    stateVersion: number;
    geoVersion: number;
  };
}

export interface FramePayload {
  frameId: number;
  tick?: number;
  humans: ActorView[];
  animals: ActorView[];
  controls: ControlSessionView[];
  events: EventView[];
}

export interface MapDeltaPayload {
  stateVersion: number;
  geoVersion: number;
  replaceAll: boolean;
  upserts: MapEntityView[];
  removed: string[];
}

export interface StatusSnapshot {
  protocol: string;
  tick: number;
  running: boolean;
  pop: number;
  entityCount: number;
  mapName: string;
}

export interface SimulationSnapshot {
  world: WorldInfo | null;
  mapEntities: Record<string, MapEntityView>;
  humans: Record<string, ActorView>;
  animals: Record<string, ActorView>;
  controls: ControlSessionView[];
  events: EventView[];
  lastFrameId: number | null;
  stateVersion: number;
  geoVersion: number;
}

export interface ViewportState {
  zoom: number;
  offsetX: number;
  offsetY: number;
}
