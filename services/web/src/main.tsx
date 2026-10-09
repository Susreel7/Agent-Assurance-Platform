import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { WindowDaysProvider } from "@/components/WindowDaysProvider";
import { ThemeProvider } from "@/components/ThemeProvider";
import "@/styles/tokens.css";
import "@/styles/global.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Most console data does not change between two adjacent clicks. Keeping it warm
      // makes back/forward and sibling-tab navigation render from memory immediately,
      // while live-tail screens retain their own explicit polling/streaming behavior.
      staleTime: 30_000,
      gcTime: 15 * 60_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

// Tenant selection is part of verified identity: Entra's tenant claim is mapped by the
// API to an account. The browser must never ask a person to type an organization UUID.
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <WindowDaysProvider>
            <App />
          </WindowDaysProvider>
        </BrowserRouter>
      </QueryClientProvider>
    </ThemeProvider>
  </React.StrictMode>,
);
