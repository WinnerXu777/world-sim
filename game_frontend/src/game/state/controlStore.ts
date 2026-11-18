import { create } from "zustand";
import { claimHumanTarget, incarnateHuman, releaseHumanTarget } from "../protocol/api";
import type { ControlSessionView } from "../protocol/types";
import { useUiStore } from "./uiStore";

type ControlState = "unclaimed" | "claiming" | "claimed" | "releasing" | "claim_failed";

interface ControlStore {
  controlState: ControlState;
  claimedTargetId: string | null;
  claimedTargetName: string | null;
  claimedMode: string | null;
  errorMessage: string | null;
  enterHumanMode: (preferredName?: string) => Promise<"entered" | "needs_name" | "failed">;
  claimTarget: (targetId: string) => Promise<void>;
  releaseTarget: () => Promise<void>;
  syncFromSession: (session: ControlSessionView | null) => void;
}

export const useControlStore = create<ControlStore>((set, get) => ({
  controlState: "unclaimed",
  claimedTargetId: null,
  claimedTargetName: null,
  claimedMode: null,
  errorMessage: null,
  async enterHumanMode(preferredName) {
    set({ controlState: "claiming", errorMessage: null });
    try {
      const result = await incarnateHuman(preferredName);
      if (!result.ok) {
        if (result.requiresName) {
          set({
            controlState: "unclaimed",
            errorMessage: null,
          });
          return "needs_name";
        }

        set({
          controlState: "claim_failed",
          errorMessage: result.reason ?? "Human mode failed",
        });
        return "failed";
      }

      set({
        controlState: "claimed",
        claimedTargetId: result.targetId ?? null,
        claimedTargetName: result.targetName ?? preferredName ?? null,
        claimedMode: result.mode ?? "incarnate",
        errorMessage: null,
      });
      useUiStore.getState().setViewMode("human");
      return "entered";
    } catch (error) {
      set({
        controlState: "claim_failed",
        errorMessage: error instanceof Error ? error.message : "Human mode failed",
      });
      return "failed";
    }
  },
  async claimTarget(targetId) {
    set({ controlState: "claiming", errorMessage: null });
    try {
      await claimHumanTarget(targetId);
      set({
        controlState: "claimed",
        claimedTargetId: targetId,
        claimedTargetName: null,
        claimedMode: "possess",
      });
      useUiStore.getState().setViewMode("human");
    } catch (error) {
      set({
        controlState: "claim_failed",
        errorMessage: error instanceof Error ? error.message : "Claim failed",
      });
    }
  },
  async releaseTarget() {
    const claimedTargetId = get().claimedTargetId;
    if (!claimedTargetId) {
      useUiStore.getState().setViewMode("god");
      set({ controlState: "unclaimed", errorMessage: null });
      return;
    }

    set({ controlState: "releasing", errorMessage: null });
    try {
      await releaseHumanTarget(claimedTargetId);
      set({
        controlState: "unclaimed",
        claimedTargetId: null,
        claimedTargetName: null,
        claimedMode: null,
      });
      useUiStore.getState().setViewMode("god");
    } catch (error) {
      set({
        controlState: "claim_failed",
        errorMessage: error instanceof Error ? error.message : "Release failed",
      });
    }
  },
  syncFromSession(session) {
    if (!session || !session.targetId) {
      set((state) => {
        if (
          state.controlState === "claiming" ||
          state.controlState === "releasing" ||
          (state.claimedTargetId == null && state.controlState === "unclaimed")
        ) {
          return state;
        }
        return {
          controlState: "unclaimed",
          claimedTargetId: null,
          claimedTargetName: null,
          claimedMode: null,
          errorMessage: null,
        };
      });
      return;
    }

    set({
      controlState: "claimed",
      claimedTargetId: session.targetId,
      claimedTargetName: session.targetName ?? null,
      claimedMode: session.mode ?? null,
      errorMessage: null,
    });
  },
}));
