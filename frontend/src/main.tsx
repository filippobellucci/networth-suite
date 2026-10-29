import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
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
