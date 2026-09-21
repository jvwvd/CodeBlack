import { Route, Routes } from "react-router-dom";

import { AppShell } from "./components/AppShell";
import { BatchPage } from "./components/BatchPage";
import { DashboardPage } from "./components/DashboardPage";
import { EmailDetailPage } from "./components/EmailDetailPage";
import { EmailList } from "./components/EmailList";
import { NotFoundPage } from "./components/NotFoundPage";
import { ReviewQueue } from "./components/ReviewQueue";
import { UploadPage } from "./components/UploadPage";

export default function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/inbox" element={<EmailList />} />
        <Route path="/emails/:emailId" element={<EmailDetailPage />} />
        <Route path="/review" element={<ReviewQueue />} />
        <Route path="/batches/:batchId" element={<BatchPage />} />
        <Route path="/upload" element={<UploadPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </AppShell>
  );
}
