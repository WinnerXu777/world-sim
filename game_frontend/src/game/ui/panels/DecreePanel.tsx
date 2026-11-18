import { useState } from "react";
import type { FormEvent } from "react";
import { submitGodDecree } from "../../protocol/api";
import { useUiStore } from "../../state/uiStore";

export function DecreePanel() {
  const decreeDraft = useUiStore((state) => state.decreeDraft);
  const setDecreeDraft = useUiStore((state) => state.setDecreeDraft);
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const text = decreeDraft.trim();
    if (!text) {
      return;
    }

    setSubmitting(true);
    setMessage(null);
    try {
      await submitGodDecree(text);
      setMessage("Decree queued.");
      setDecreeDraft("");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Decree failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="panel">
      <div className="panel__header">
        <h3>God Decree</h3>
      </div>
      <div className="panel__body">
        <form className="decree-form" onSubmit={(event) => void onSubmit(event)}>
          <textarea
            placeholder="Send wolves into the forest. Build a shelter near the river."
            value={decreeDraft}
            onChange={(event) => setDecreeDraft(event.target.value)}
          />
          <div className="decree-form__footer">
            <span>{message ?? "Structured or natural-language decrees both fit here."}</span>
            <button className="action-button" data-variant="primary" disabled={submitting} type="submit">
              {submitting ? "Sending..." : "Send Decree"}
            </button>
          </div>
        </form>
      </div>
    </section>
  );
}
