import { useEffect } from "react";
import { AppProviders } from "./providers";
import { AppRouter } from "./router";
import { useSimulationBootstrap } from "../game/protocol/polling";

function AppContent() {
  useSimulationBootstrap();

  return <AppRouter />;
}

export function App() {
  useEffect(() => {
    document.title = "Eden Chronicle";
  }, []);

  return (
    <AppProviders>
      <AppContent />
    </AppProviders>
  );
}
