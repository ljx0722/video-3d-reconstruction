import { Routes, Route } from 'react-router-dom';
import Header from './components/Header';
import UploadZone from './components/UploadZone';
import JobList from './components/JobList';
import ViewerPage from './viewer/ViewerPage';

export default function App() {
  return (
    <div className="min-h-screen flex flex-col">
      <Header />
      <main className="flex-1">
        <Routes>
          <Route path="/" element={<UploadZone />} />
          <Route path="/jobs" element={<JobList />} />
          <Route path="/viewer/:jobId" element={<ViewerPage />} />
        </Routes>
      </main>
    </div>
  );
}
