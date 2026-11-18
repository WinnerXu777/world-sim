import { create } from "zustand";
import type { ViewMode, ViewportState } from "../protocol/types";

type PanelKey = "status" | "inspect" | "decree" | "events";

interface UiStore {
  viewMode: ViewMode;
  viewport: ViewportState;
  decreeDraft: string;
  humanZoom: number;
  showStatusPanel: boolean;
  showInspectPanel: boolean;
  showDecreePanel: boolean;
  showEventPanel: boolean;
  humanSidecarOpen: boolean;
  setViewMode: (mode: ViewMode) => void;
  setViewport: (viewport: Partial<ViewportState>) => void;
  setDecreeDraft: (value: string) => void;
  setHumanZoom: (zoom: number) => void;
  adjustHumanZoom: (delta: number) => void;
  togglePanel: (panel: PanelKey) => void;
  setPanelVisible: (panel: PanelKey, visible: boolean) => void;
  toggleHumanSidecar: () => void;
  setHumanSidecarOpen: (open: boolean) => void;
}

export const useUiStore = create<UiStore>((set) => ({
  viewMode: "god",
  viewport: {
    zoom: 0.7,
    offsetX: 24,
    offsetY: 24,
  },
  decreeDraft: "",
  humanZoom: 0.58,
  showStatusPanel: true,
  showInspectPanel: true,
  showDecreePanel: false,
  showEventPanel: false,
  humanSidecarOpen: false,
  setViewMode(viewMode) {
    set({ viewMode });
  },
  setViewport(viewport) {
    set((state) => ({
      viewport: {
        ...state.viewport,
        ...viewport,
      },
    }));
  },
  setDecreeDraft(decreeDraft) {
    set({ decreeDraft });
  },
  setHumanZoom(humanZoom) {
    set({
      humanZoom: Math.max(0, Math.min(1, humanZoom)),
    });
  },
  adjustHumanZoom(delta) {
    set((state) => ({
      humanZoom: Math.max(0, Math.min(1, state.humanZoom + delta)),
    }));
  },
  togglePanel(panel) {
    set((state) => {
      const key =
        panel === "status"
          ? "showStatusPanel"
          : panel === "inspect"
            ? "showInspectPanel"
            : panel === "decree"
              ? "showDecreePanel"
              : "showEventPanel";
      return {
        [key]: !state[key],
      } as Pick<
        UiStore,
        "showStatusPanel" | "showInspectPanel" | "showDecreePanel" | "showEventPanel"
      >;
    });
  },
  setPanelVisible(panel, visible) {
    set({
      [panel === "status"
        ? "showStatusPanel"
        : panel === "inspect"
          ? "showInspectPanel"
          : panel === "decree"
            ? "showDecreePanel"
            : "showEventPanel"]: visible,
    } as Pick<
      UiStore,
      "showStatusPanel" | "showInspectPanel" | "showDecreePanel" | "showEventPanel"
    >);
  },
  toggleHumanSidecar() {
    set((state) => ({
      humanSidecarOpen: !state.humanSidecarOpen,
    }));
  },
  setHumanSidecarOpen(humanSidecarOpen) {
    set({ humanSidecarOpen });
  },
}));
