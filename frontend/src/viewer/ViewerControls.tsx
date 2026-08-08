import type { Job } from '../types';

interface Props {
  job: Job;
}

export default function ViewerControls({ job }: Props) {
  return (
    <div className="absolute top-4 left-4 bg-gray-900/80 backdrop-blur rounded-lg p-3 text-xs space-y-1 z-10">
      <p><span className="text-gray-500">Job:</span> {job.id.slice(0, 8)}...</p>
      {job.num_frames && <p><span className="text-gray-500">Frames:</span> {job.num_frames}</p>}
      {job.num_points && <p><span className="text-gray-500">Points:</span> {(job.num_points / 1_000_000).toFixed(1)}M</p>}
      {job.processing_time_secs && <p><span className="text-gray-500">Time:</span> {job.processing_time_secs.toFixed(1)}s</p>}
    </div>
  );
}
