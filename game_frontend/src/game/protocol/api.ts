import { bootstrapSchema, frameSchema, mapDeltaSchema, statusSchema } from "./schema";
import type {
  BootstrapPayload,
  ControlActionResult,
  FramePayload,
  MapDeltaPayload,
  StatusSnapshot,
} from "./types";

const DEFAULT_BACKEND_URL = "http://127.0.0.1:8002";
let controlSequence = 1;
let sessionCapability = "";
let capabilityRequest: Promise<string> | null = null;

async function backendFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const method = (init.method ?? "GET").toUpperCase();
  if (!["GET", "HEAD", "OPTIONS"].includes(method) && !sessionCapability) {
    capabilityRequest ??= fetch(`${backendUrl()}/bootstrap`)
      .then(async (response) => {
        if (!response.ok) throw new Error(`Session bootstrap failed: ${response.status}`);
        const payload = await response.json();
        if (typeof payload.session_capability !== "string" || !payload.session_capability) {
          throw new Error("Backend did not provide a local session capability");
        }
        return payload.session_capability as string;
      });
    try {
      sessionCapability = await capabilityRequest;
    } finally {
      capabilityRequest = null;
    }
  }
  const headers = new Headers(init.headers);
  if (sessionCapability) headers.set("X-Eden-Session", sessionCapability);
  const response = await fetch(`${backendUrl()}${path}`, { ...init, headers });
  if (response.status === 401) sessionCapability = "";
  // Do not replay mutations automatically when a restarted server rejects a token.
  return response;
}

function backendUrl() {
  const envUrl =
    typeof import.meta !== "undefined" && import.meta.env.VITE_BACKEND_URL
      ? import.meta.env.VITE_BACKEND_URL
      : undefined;

  return (envUrl ?? DEFAULT_BACKEND_URL).replace(/\/$/, "");
}

async function requestJson<T>(
  path: string,
  init: RequestInit,
  parser: { parse: (value: unknown) => T },
): Promise<T> {
  const response = await backendFetch(path, {
    headers: {
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
    },
    ...init,
  });

  if (!response.ok) {
    throw new Error(`Request failed for ${path}: ${response.status}`);
  }

  const json = (await response.json()) as unknown;
  return parser.parse(json);
}

function normalizeControlActionResult(value: unknown, fallbackOk: boolean): ControlActionResult {
  const payload = typeof value === "object" && value !== null ? (value as Record<string, unknown>) : {};
  return {
    ok: typeof payload.ok === "boolean" ? payload.ok : fallbackOk,
    reason: typeof payload.reason === "string" ? payload.reason : undefined,
    requiresName: Boolean(payload.requires_name),
    controllerId: typeof payload.controller_id === "string" ? payload.controller_id : undefined,
    targetId: typeof payload.target_id === "string" ? payload.target_id : undefined,
    targetKind: typeof payload.target_kind === "string" ? payload.target_kind : undefined,
    targetName: typeof payload.target_name === "string" ? payload.target_name : undefined,
    mode: typeof payload.mode === "string" ? payload.mode : undefined,
    spawned: typeof payload.spawned === "boolean" ? payload.spawned : undefined,
    incarnation: typeof payload.incarnation === "string" ? payload.incarnation : undefined,
  };
}

export async function fetchBootstrap(): Promise<BootstrapPayload> {
  return requestJson("/bootstrap", { method: "GET" }, bootstrapSchema);
}

export async function fetchFrame(): Promise<FramePayload> {
  return requestJson("/frame", { method: "GET" }, frameSchema);
}

export async function fetchMapDelta(
  stateVersion: number,
  geoVersion: number,
): Promise<MapDeltaPayload> {
  const path = `/map_delta?since_state_version=${stateVersion}&since_geo_version=${geoVersion}`;
  return requestJson(path, { method: "GET" }, mapDeltaSchema);
}

export async function fetchStatus(): Promise<StatusSnapshot> {
  return requestJson("/status", { method: "GET" }, statusSchema);
}

export async function submitGodDecree(text: string) {
  const body = JSON.stringify({ god_decree: text });
  const response = await backendFetch("/god_decree", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body,
  });

  if (!response.ok) {
    throw new Error(`God decree failed: ${response.status}`);
  }

  return response.json();
}

export async function claimHumanTarget(targetId: string) {
  const response = await backendFetch("/control/claim", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      controller_id: "local_player",
      target_kind: "human",
      target_id: targetId,
      context: "human_web",
      view_style: "top_down",
    }),
  });

  if (!response.ok) {
    throw new Error(`Claim failed: ${response.status}`);
  }

  return response.json();
}

export async function incarnateHuman(preferredName?: string): Promise<ControlActionResult> {
  const response = await backendFetch("/control/incarnate", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      controller_id: "local_player",
      preferred_name: preferredName,
    }),
  });

  let payload: unknown = {};
  try {
    payload = await response.json();
  } catch {
    payload = {};
  }

  const result = normalizeControlActionResult(payload, response.ok);
  if (!response.ok && !result.requiresName) {
    throw new Error(result.reason ? `Incarnation failed: ${result.reason}` : `Incarnation failed: ${response.status}`);
  }

  return result;
}

export async function releaseHumanTarget(targetId: string) {
  const response = await backendFetch("/control/release", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      controller_id: "local_player",
      target_kind: "human",
      target_id: targetId,
    }),
  });

  if (!response.ok) {
    throw new Error(`Release failed: ${response.status}`);
  }

  return response.json();
}

function nextControlSequence() {
  const current = controlSequence;
  controlSequence += 1;
  return current;
}

export async function sendControlInput(payload: {
  targetId: string;
  moveX: number;
  moveY: number;
  sprint: boolean;
}) {
  const response = await backendFetch("/control/input", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      controller_id: "local_player",
      target_kind: "human",
      target_id: payload.targetId,
      seq: nextControlSequence(),
      context: "human_web",
      view_style: "high_angle",
      move: {
        x: payload.moveX,
        y: payload.moveY,
      },
      buttons: {
        attack: false,
        interact: false,
        sprint: payload.sprint,
      },
    }),
  });

  if (!response.ok) {
    throw new Error(`Control input failed: ${response.status}`);
  }
}

export async function sendControlEvent(payload: {
  action: "attack" | "talk" | "interact";
  controlledTargetId: string;
  selectedTargetId?: string | null;
  selectedTargetKind?: string | null;
  selectedTargetName?: string | null;
  text?: string;
}) {
  const response = await backendFetch("/control/event", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      controller_id: "local_player",
      seq: nextControlSequence(),
      context: "human_web",
      view_style: "high_angle",
      event: "click_command",
      action: payload.action,
      target_kind: payload.selectedTargetKind ?? "",
      target_id: payload.selectedTargetId ?? "",
      target_name: payload.selectedTargetName ?? "",
      controlled_target_id: payload.controlledTargetId,
      text: payload.text,
    }),
  });

  if (!response.ok) {
    throw new Error(`Control event failed: ${response.status}`);
  }

  return response.json();
}
