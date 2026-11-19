import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { reportError } from "./api";
import "./index.css";

window.addEventListener("error", (e) => reportError("window.onerror", e.error ?? e.message));
window.addEventListener("unhandledrejection", (e) => reportError("unhandledrejection", e.reason));

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
