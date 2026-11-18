import { create } from "zustand";
import { fetchBootstrap } from "../protocol/api";
import type {
  ActorView,
  BootstrapPayload,
  FramePayload,
  MapDeltaPayload,
  MapEntityView,
  NetworkState,
  SimulationSnapshot,
  StatusSnapshot,
} from "../protocol/types";

interface SimulationStore extends SimulationSnapshot {
  networkState: NetworkState;
  errorMessage: string | null;
  status: StatusSnapshot | null;
  bootstrap: () => Promise<void>;
  applyBootstrap: (payload: BootstrapPayload) => void;
  applyFrame: (payload: FramePayload) => void;
  applyMapDelta: (payload: MapDeltaPayload) => void;
  setStatus: (status: StatusSnapshot) => void;
  setError: (message: string | null) => void;
}

function byId<T extends { id: string }>(values: T[]) {
  return Object.fromEntries(values.map((value) => [value.id, value]));
}

function mergeEvents(existing: Record<string, ActorView>, incoming: ActorView[]) {
  const merged = { ...existing };
  for (const actor of incoming) {
    merged[actor.id] = actor;
  }
  return merged;
}

export const useSimulationStore = create<SimulationStore>((set) => ({
  world: null,
  mapEntities: {},
  humans: {},
  animals: {},
  controls: [],
  events: [],
  lastFrameId: null,
  stateVersion: -1,
  geoVersion: -1,
  networkState: "connecting",
  errorMessage: null,
  status: null,
  async bootstrap() {
    set({ networkState: "connecting", errorMessage: null });
    try {
      const payload = await fetchBootstrap();
      useSimulationStore.getState().applyBootstrap(payload);
    } catch (error) {
      set({
        networkState: "error",
        errorMessage: error instanceof Error ? error.message : "Bootstrap failed",
      });
    }
  },
  applyBootstrap(payload) {
    set({
      world: payload.world,
      mapEntities: byId(payload.map.entities),
      stateVersion: payload.map.stateVersion,
      geoVersion: payload.map.geoVersion,
      networkState: "connected",
      errorMessage: null,
    });
  },
  applyFrame(payload) {
    set((state) => ({
      humans: mergeEvents(state.humans, payload.humans),
      animals: mergeEvents(state.animals, payload.animals),
      controls: payload.controls,
      events: payload.events.slice(-20).reverse(),
      lastFrameId: payload.frameId,
      networkState: "connected",
      errorMessage: null,
    }));
  },
  applyMapDelta(payload) {
    set((state) => {
      const nextMapEntities: Record<string, MapEntityView> = payload.replaceAll
        ? byId(payload.upserts)
        : { ...state.mapEntities };

      if (!payload.replaceAll) {
        for (const entity of payload.upserts) {
          nextMapEntities[entity.id] = entity;
        }
      }

      for (const entityId of payload.removed) {
        delete nextMapEntities[entityId];
      }

      return {
        mapEntities: nextMapEntities,
        stateVersion: payload.stateVersion,
        geoVersion: payload.geoVersion,
      };
    });
  },
  setStatus(status) {
    set({ status });
  },
  setError(message) {
    set({
      errorMessage: message,
      networkState: message ? "degraded" : "connected",
    });
  },
}));
