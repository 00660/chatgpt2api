import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";

import { AppLayout } from "@/App";
import AccountsPage from "@/app/accounts/page";
import ApiDocsPage from "@/app/api-docs/page";
import ChannelsPage from "@/app/channels/page";
import ChatPage from "@/app/chat/page";
import DebugPage from "@/app/debug/page";
import ImagePage from "@/app/image/page";
import ImageManagerPage from "@/app/image-manager/page";
import LogsPage from "@/app/logs/page";
import LoginPage from "@/app/login/page";
import HomePage from "@/app/page";
import PptPage from "@/app/ppt/page";
import PsdPage from "@/app/psd/page";
import RegisterPage from "@/app/register/page";
import SearchPage from "@/app/search/page";
import SettingsPage from "@/app/settings/page";
import "./app/globals.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route element={<AppLayout />}>
          <Route path="/" element={<HomePage />} />
          <Route path="/login" element={<LoginPage />} />
          <Route path="/chat" element={<ChatPage />} />
          <Route path="/search" element={<SearchPage />} />
          <Route path="/image" element={<ImagePage />} />
          <Route path="/accounts" element={<AccountsPage />} />
          <Route path="/channels" element={<ChannelsPage />} />
          <Route path="/api-docs" element={<ApiDocsPage />} />
          <Route path="/ppt" element={<PptPage />} />
          <Route path="/psd" element={<PsdPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route path="/image-manager" element={<ImageManagerPage />} />
          <Route path="/logs" element={<LogsPage />} />
          <Route path="/debug" element={<DebugPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </StrictMode>,
);
