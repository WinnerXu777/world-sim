import { useSimulationStore } from "../../state/simStore";

export function EventFeedPanel() {
  const events = useSimulationStore((state) => state.events);

  return (
    <section className="panel">
      <div className="panel__header">
        <h3>Recent Events</h3>
      </div>
      <div className="panel__body">
        {events.length === 0 ? (
          <div className="empty-state">No recent events yet.</div>
        ) : (
          <div className="event-list">
            {events.map((event) => (
              <div className="event-item" key={event.id}>
                <strong>{event.text}</strong>
                <div className="event-item__meta">
                  {event.category ?? "sim"} {event.tick ? `- tick ${event.tick}` : ""}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
