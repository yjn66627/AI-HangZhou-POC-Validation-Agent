import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import AppShell from "./components/AppShell";
import HomePage from "./pages/HomePage";
import RequirementPage from "./pages/RequirementPage";
import CandidatesPage from "./pages/CandidatesPage";
import ProgressPage from "./pages/ProgressPage";
import ComparisonPage from "./pages/ComparisonPage";
import EvidencePage from "./pages/EvidencePage";
import DecisionPage from "./pages/DecisionPage";
import ExceptionPage from "./pages/ExceptionPage";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/cases/:id" element={<AppShell />}>
          <Route index element={<Navigate to="requirement" replace />} />
          <Route path="requirement" element={<RequirementPage />} />
          <Route path="candidates" element={<CandidatesPage />} />
          <Route path="progress" element={<ProgressPage />} />
          <Route path="comparison" element={<ComparisonPage />} />
          <Route path="evidence" element={<EvidencePage />} />
          <Route path="decision" element={<DecisionPage />} />
          <Route path="exception" element={<ExceptionPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>,
);
