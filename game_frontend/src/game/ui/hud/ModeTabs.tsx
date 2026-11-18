import type { ViewMode } from "../../protocol/types";

interface ModeTabsProps {
  mode: ViewMode;
  onSelect: (mode: ViewMode) => void;
}

export function ModeTabs({ mode, onSelect }: ModeTabsProps) {
  return (
    <div className="mode-tabs">
      <button data-active={mode === "god"} onClick={() => onSelect("god")} type="button">
        God Mode
      </button>
      <button data-active={mode === "human"} onClick={() => onSelect("human")} type="button">
        Human Mode
      </button>
    </div>
  );
}
