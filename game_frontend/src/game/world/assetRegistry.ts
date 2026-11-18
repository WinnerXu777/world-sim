/**
 * assetRegistry.ts
 * =================
 * Maps backend entity type labels to 3D model paths and rendering config.
 *
 * Entity labels come from genesis_config.py MAP_SCHEMA[M_TYPE]["label"]
 * and arrive on the frontend via the `typeLabel` field on MapEntityView.
 */

// ---------------------------------------------------------------------------
// Model path constants (served from public/)
// ---------------------------------------------------------------------------

const NATURE = "/models/nature";
const PROPS = "/models/props";
const VILLAGE = "/models/village";

// ---------------------------------------------------------------------------
// Asset entry type
// ---------------------------------------------------------------------------

export interface AssetEntry {
  /** Path to the .gltf file relative to public root */
  path: string;
  /** Uniform scale multiplier applied to the loaded model */
  scale: number;
  /** Y-axis rotation in radians (for random orientation, set randomRotateY) */
  rotationY?: number;
  /** If true, each instance gets a random Y rotation */
  randomRotateY?: boolean;
  /** Optional Y offset to raise/lower the model */
  offsetY?: number;
  /** Optional color tint override (hex string) */
  tint?: string;
  /** When multiple variants exist, these are alternates chosen by hash */
  variants?: Omit<AssetEntry, "variants">[];
}

// ---------------------------------------------------------------------------
// Entity label → asset mapping
// ---------------------------------------------------------------------------

export const ENTITY_ASSETS: Record<string, AssetEntry> = {
  // ── Natural features ────────────────────────────────────────────────────
  forest: {
    path: `${NATURE}/CommonTree_1.gltf`,
    scale: 8,
    randomRotateY: true,
    variants: [
      { path: `${NATURE}/CommonTree_2.gltf`, scale: 8, randomRotateY: true },
      { path: `${NATURE}/CommonTree_3.gltf`, scale: 7, randomRotateY: true },
      { path: `${NATURE}/Pine_1.gltf`, scale: 8, randomRotateY: true },
      { path: `${NATURE}/Pine_2.gltf`, scale: 9, randomRotateY: true },
    ],
  },

  grassland: {
    path: `${NATURE}/Bush_Common.gltf`,
    scale: 5,
    randomRotateY: true,
    variants: [
      { path: `${NATURE}/Grass_Common_Short.gltf`, scale: 6, randomRotateY: true },
      { path: `${NATURE}/Fern_1.gltf`, scale: 5, randomRotateY: true },
    ],
  },

  mountain: {
    path: `${NATURE}/Rock_Medium_1.gltf`,
    scale: 14,
    randomRotateY: true,
    variants: [
      { path: `${NATURE}/Rock_Medium_2.gltf`, scale: 16, randomRotateY: true },
      { path: `${NATURE}/Rock_Medium_3.gltf`, scale: 12, randomRotateY: true },
    ],
  },

  beach: {
    path: `${NATURE}/Pebble_Round_1.gltf`,
    scale: 6,
    randomRotateY: true,
    tint: "#e8d5a3",
  },

  barren: {
    path: `${NATURE}/DeadTree_1.gltf`,
    scale: 7,
    randomRotateY: true,
    tint: "#8c7b6b",
  },

  // ── Structures ──────────────────────────────────────────────────────────
  house: {
    path: `${VILLAGE}/Wall_Plaster_Straight.gltf`,
    scale: 10,
    offsetY: 0,
    variants: [
      { path: `${VILLAGE}/Wall_Plaster_Door_Flat.gltf`, scale: 10 },
    ],
  },

  village: {
    path: `${PROPS}/Stall_Empty.gltf`,
    scale: 12,
    randomRotateY: true,
  },

  farm: {
    path: `${PROPS}/FarmCrate_Empty.gltf`,
    scale: 8,
    randomRotateY: true,
    variants: [
      { path: `${VILLAGE}/Prop_WoodenFence_Single.gltf`, scale: 8, randomRotateY: true },
    ],
  },

  well: {
    path: `${PROPS}/Bucket_Wooden_1.gltf`,
    scale: 10,
  },

  wall: {
    path: `${VILLAGE}/Wall_Plaster_Straight.gltf`,
    scale: 8,
  },

  storage_case: {
    path: `${PROPS}/Chest_Wood.gltf`,
    scale: 8,
    randomRotateY: true,
    variants: [
      { path: `${PROPS}/Crate_Wooden.gltf`, scale: 8, randomRotateY: true },
      { path: `${PROPS}/Barrel.gltf`, scale: 8, randomRotateY: true },
    ],
  },
};

// ---------------------------------------------------------------------------
// Scatter decoration models (placed around entity centres for atmosphere)
// ---------------------------------------------------------------------------

export interface ScatterEntry {
  path: string;
  scale: number;
  /** Max distance from entity centre to scatter instances */
  radius: number;
  /** How many to scatter per entity */
  count: number;
}

export const ENTITY_SCATTER: Record<string, ScatterEntry[]> = {
  forest: [
    { path: `${NATURE}/Bush_Common.gltf`, scale: 3, radius: 0.6, count: 2 },
    { path: `${NATURE}/Mushroom_Common.gltf`, scale: 3, radius: 0.5, count: 1 },
    { path: `${NATURE}/Grass_Common_Short.gltf`, scale: 4, radius: 0.7, count: 2 },
  ],
  grassland: [
    { path: `${NATURE}/Grass_Common_Short.gltf`, scale: 4, radius: 0.6, count: 3 },
    { path: `${NATURE}/Fern_1.gltf`, scale: 3, radius: 0.5, count: 1 },
  ],
  mountain: [
    { path: `${NATURE}/Pebble_Round_1.gltf`, scale: 4, radius: 0.5, count: 2 },
  ],
  village: [
    { path: `${PROPS}/Barrel.gltf`, scale: 5, radius: 0.4, count: 1 },
    { path: `${PROPS}/Bench.gltf`, scale: 5, radius: 0.3, count: 1 },
    { path: `${PROPS}/Torch_Metal.gltf`, scale: 5, radius: 0.3, count: 1 },
  ],
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Simple hash for deterministic variant selection from an entity id */
function hashId(id: string): number {
  let hash = 0;
  for (let i = 0; i < id.length; i++) {
    hash = (hash * 31 + id.charCodeAt(i)) | 0;
  }
  return Math.abs(hash);
}

/** Pick the right asset entry for an entity, choosing a variant by id hash */
export function resolveAsset(
  typeLabel: string | undefined,
  entityId: string,
): AssetEntry | null {
  if (!typeLabel) return null;
  const entry = ENTITY_ASSETS[typeLabel];
  if (!entry) return null;

  if (entry.variants && entry.variants.length > 0) {
    const allOptions = [entry, ...entry.variants];
    const idx = hashId(entityId) % allOptions.length;
    const picked = allOptions[idx];
    return { ...picked, variants: undefined };
  }

  return entry;
}

/** Get a deterministic pseudo-random rotation for an entity */
export function entityRotation(entityId: string): number {
  return (hashId(entityId) % 628) / 100; // 0 to ~2π
}

/** Collect all model paths that should be preloaded */
export function getAllModelPaths(): string[] {
  const paths = new Set<string>();
  for (const entry of Object.values(ENTITY_ASSETS)) {
    paths.add(entry.path);
    if (entry.variants) {
      for (const v of entry.variants) {
        paths.add(v.path);
      }
    }
  }
  for (const scatterList of Object.values(ENTITY_SCATTER)) {
    for (const s of scatterList) {
      paths.add(s.path);
    }
  }
  return [...paths];
}
