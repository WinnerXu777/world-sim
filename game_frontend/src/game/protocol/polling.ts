import { useEffect } from "react";
import { fetchBootstrap, fetchFrame, fetchMapDelta, fetchStatus } from "./api";
import { useControlStore } from "../state/controlStore";
import { useSimulationStore } from "../state/simStore";

export function useSimulationBootstrap() {
  const bootstrap = useSimulationStore((state) => state.bootstrap);
  const world = useSimulationStore((state) => state.world);

  useEffect(() => {
    void bootstrap();
  }, [bootstrap]);

  useEffect(() => {
    let cancelled = false;

    async function pollStatus() {
      try {
        const status = await fetchStatus();
        if (!cancelled) {
          useSimulationStore.getState().setStatus(status);
        }
      } catch (error) {
        if (!cancelled) {
          useSimulationStore.getState().setError(
            error instanceof Error ? error.message : "Status request failed",
          );
        }
      }
    }

    void pollStatus();
    const interval = window.setInterval(() => {
      void pollStatus();
    }, 4000);

    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function pollFrame() {
      const store = useSimulationStore.getState();
      if (!store.world) {
        return;
      }

      try {
        const payload = await fetchFrame();
        if (!cancelled) {
          useSimulationStore.getState().applyFrame(payload);
          const localSession =
            payload.controls.find((control) => control.controllerId === "local_player") ?? null;
          useControlStore.getState().syncFromSession(localSession);
        }
      } catch (error) {
        if (!cancelled) {
          useSimulationStore.getState().setError(
            error instanceof Error ? error.message : "Frame request failed",
          );
        }
      }
    }

    if (world) {
      void pollFrame();
    }
    const interval = window.setInterval(() => {
      void pollFrame();
    }, 350);

    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [world]);

  useEffect(() => {
    let cancelled = false;

    async function pollMap() {
      const store = useSimulationStore.getState();
      if (!store.world) {
        return;
      }

      try {
        const payload = await fetchMapDelta(store.stateVersion, store.geoVersion);
        if (!cancelled) {
          useSimulationStore.getState().applyMapDelta(payload);
        }
      } catch (error) {
        if (!cancelled) {
          useSimulationStore.getState().setError(
            error instanceof Error ? error.message : "Map delta request failed",
          );
        }
      }
    }

    if (world) {
      void pollMap();
    }
    const interval = window.setInterval(() => {
      void pollMap();
    }, 1000);

    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [world]);
}
