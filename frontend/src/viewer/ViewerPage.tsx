import { useParams, Link } from 'react-router-dom';
import useSWR from 'swr';
import { getJob } from '../api/client';
import ViewerCanvas from './ViewerCanvas';
import ViewerControls from './ViewerControls';
import type { Job } from '../types';

export default function ViewerPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const { data: job, error } = useSWR<Job>(jobId ? `job-${jobId}` : null, () => getJob(jobId!), { refreshInterval: 2000 });

  if (error) return <p className="text-center text-red-400 mt-12">Failed to load job</p>;
  if (!job) return <p className="text-center text-gray-500 mt-12">Loading...</p>;

  if (job.status === 'uploaded' || job.status === 'queued' || job.status === 'processing') {
    return (
      <div className="max-w-lg mx-auto px-4 pt-24 text-center">
        <div className="w-16 h-16 mx-auto mb-4 border-4 border-blue-500 border-t-transparent rounded-full animate-spin" />
        <h2 className="text-xl font-semibold mb-2">Processing video...</h2>
        <p className="text-gray-400 mb-4">Status: {job.status}</p>
        <div className="w-full bg-gray-800 rounded-full h-2">
          <div className="bg-blue-500 h-2 rounded-full transition-all" style={{ width: `${(job.progress || 0) * 100}%` }} />
        </div>
      </div>
    );
  }

  if (job.status === 'failed') {
    return (
      <div className="max-w-lg mx-auto px-4 pt-24 text-center">
        <h2 className="text-xl font-semibold text-red-400 mb-2">Processing failed</h2>
        <p className="text-gray-400 mb-4">{job.error_message || 'Unknown error'}</p>
        <Link to="/" className="text-blue-400 hover:underline">Try again</Link>
      </div>
    );
  }

  return (
    <div className="relative h-[calc(100vh-3.5rem)]">
      <ViewerCanvas jobId={job.id} />
      <ViewerControls job={job} />
    </div>
  );
}
