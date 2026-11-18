import { useEffect, useRef } from "react";
import { sendControlInput } from "../protocol/api";
import { useControlStore } from "../state/controlStore";
import { useUiStore } from "../state/uiStore";
import { humanMovementBasis } from "../world/humanView";

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

function isTextInputTarget(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) {
    return false;
  }

  const tag = target.tagName.toLowerCase();
  return tag === "input" || tag === "textarea" || target.isContentEditable;
}

export function useHumanControlLoop() {
  const viewMode = useUiStore((state) => state.viewMode);
  const claimedTargetId = useControlStore((state) => state.claimedTargetId);
  const pressedKeys = useRef<Set<string>>(new Set());
  const lastSignature = useRef<string>("");

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (isTextInputTarget(event.target)) {
        return;
      }
      pressedKeys.current.add(event.code);
    }

    function onKeyUp(event: KeyboardEvent) {
      pressedKeys.current.delete(event.code);
    }

    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);

    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
    };
  }, []);

  useEffect(() => {
    if (viewMode !== "human" || !claimedTargetId) {
      lastSignature.current = "";
      return;
    }

    const interval = window.setInterval(() => {
      const keys = pressedKeys.current;
      const basis = humanMovementBasis();
      let moveX = 0;
      let moveY = 0;

      if (keys.has("KeyA")) {
        moveX -= basis.right.x;
        moveY -= basis.right.y;
      }
      if (keys.has("KeyD")) {
        moveX += basis.right.x;
        moveY += basis.right.y;
      }
      if (keys.has("KeyW")) {
        moveX += basis.forward.x;
        moveY += basis.forward.y;
      }
      if (keys.has("KeyS")) {
        moveX -= basis.forward.x;
        moveY -= basis.forward.y;
      }

      const normalized = normalizeVector(moveX, moveY);
      const sprint = keys.has("ShiftLeft") || keys.has("ShiftRight");
      const signature = `${normalized.x.toFixed(3)}:${normalized.y.toFixed(3)}:${sprint}`;

      if (signature === lastSignature.current) {
        return;
      }

      lastSignature.current = signature;
      void sendControlInput({
        targetId: claimedTargetId,
        moveX: normalized.x,
        moveY: normalized.y,
        sprint,
      });
    }, 90);

    return () => {
      window.clearInterval(interval);
    };
  }, [claimedTargetId, viewMode]);
}
