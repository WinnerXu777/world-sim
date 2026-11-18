import type { WorldInfo } from "../protocol/types";

export const HUMAN_CAMERA_OFFSET = {
  x: 16,
  y: 18,
} as const;

export const HUMAN_ZOOM_MIN = 0;
export const HUMAN_ZOOM_MAX = 1;

function normalizeVector(x: number, y: number) {
  const length = Math.hypot(x, y);
  if (length <= 0) {
    return { x: 0, y: 0 };
  }
  return {
    x: x / length,
    y: y / length,
  };
}

export function humanCameraHeight(world: WorldInfo) {
  return Math.max(24, Math.max(world.width, world.height) * 0.018 + 18);
}

export function humanZoomDistanceScale(zoom: number) {
  return 0.62 + (1 - zoom) * 1.38;
}

export function humanMovementBasis() {
  const forward = normalizeVector(-HUMAN_CAMERA_OFFSET.x, -HUMAN_CAMERA_OFFSET.y);
  return {
    forward,
    right: {
      x: -forward.y,
      y: forward.x,
    },
  };
}
