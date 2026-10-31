import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
// Fonts are bundled, not fetched from Google: the app contacts no third party.
// Only the weights in use: Inter 300-700, IBM Plex Mono 400-600.
import "@fontsource/inter/300.css";
import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";
import "@fontsource/inter/700.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "@fontsource/ibm-plex-mono/600.css";
import "./index.css";
import App from "./App.tsx";
import { ThemeProvider } from "./context/ThemeContext";
import { PaletteProvider } from "./context/PaletteContext";
import { PortfolioProvider } from "./context/PortfolioContext";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ThemeProvider>
      <PaletteProvider>
        <BrowserRouter>
          <PortfolioProvider>
            <App />
          </PortfolioProvider>
        </BrowserRouter>
      </PaletteProvider>
    </ThemeProvider>
  </StrictMode>
);
