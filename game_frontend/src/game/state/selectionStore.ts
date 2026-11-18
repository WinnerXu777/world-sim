import { create } from "zustand";

type SelectionKind = "human" | "animal" | "entity";

interface SelectionState {
  selectedId: string | null;
  selectedKind: SelectionKind | null;
  setSelection: (kind: SelectionKind, id: string) => void;
  clearSelection: () => void;
}

export const useSelectionStore = create<SelectionState>((set) => ({
  selectedId: null,
  selectedKind: null,
  setSelection(kind, id) {
    set({
      selectedId: id,
      selectedKind: kind,
    });
  },
  clearSelection() {
    set({
      selectedId: null,
      selectedKind: null,
    });
  },
}));
