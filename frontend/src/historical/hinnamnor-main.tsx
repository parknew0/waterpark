import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { HinnamnorReplayApp } from "./HinnamnorReplayApp";
import "./hinnamnor.css";

createRoot(document.getElementById("hinnamnor-root")!).render(
  <StrictMode>
    <HinnamnorReplayApp />
  </StrictMode>,
);
