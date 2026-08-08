import { useParams, Link } from 'react-router-dom';
import useSWR from 'swr';
import { getJob } from '../api/client';
import ViewerCanvas from './ViewerCanvas';
import ViewerControls from './ViewerControls';
import type { Job } from '../types';

const statusMap: Record<string, string> = {
  uploaded: '已上传',
  queued: '等待GPU处理',
  processing: 'GPU处理中',
  completed: '处理完成',
  failed: '处理失败',
};

export default function ViewerPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const { data: job, error } = useSWR<Job>(jobId ? `job-${jobId}` : null, () => getJob(jobId!), { refreshInterval: 2000 });

  if (error) return <p className="text-center text-red-400 mt-12">加载作业失败</p>;
  if (!job) return (
    <div className="max-w-lg mx-auto px-4 pt-24 text-center">
      <div className="w-16 h-16 mx-auto mb-4 border-4 border-blue-500 border-t-transparent rounded-full animate-spin" />
      <p className="text-gray-400">加载作业信息...</p>
    </div>
  );

  if (job.status === 'uploaded' || job.status === 'queued' || job.status === 'processing') {
    const statusLabel = statusMap[job.status] || job.status;
    const rawProgress = (job.progress || 0) * 100;
    const progressPct = Math.max(2, Math.min(100, rawProgress));
    return (
      <div className="max-w-lg mx-auto px-4 pt-24 text-center">
        <div className="w-20 h-20 mx-auto mb-6 relative">
          <svg className="animate-spin w-20 h-20" viewBox="0 0 80 80">
            <circle cx="40" cy="40" r="34" fill="none" stroke="#1f2937" strokeWidth="6" />
            <circle cx="40" cy="40" r="34" fill="none" stroke="url(#grad)" strokeWidth="6" strokeLinecap="round"
              strokeDasharray={`${2.1 * progressPct} ${210 - 2.1 * progressPct}`} transform="rotate(-90 40 40)" />
            <defs>
              <linearGradient id="grad" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0%" stopColor="#3B82F6" />
                <stop offset="100%" stopColor="#7C3AED" />
              </linearGradient>
            </defs>
          </svg>
          <span className="absolute inset-0 flex items-center justify-center text-sm font-semibold">
            {Math.round(progressPct)}%
          </span>
        </div>
        <h2 className="text-xl font-semibold mb-2">{statusLabel}</h2>
        <p className="text-gray-500 text-sm mb-6">视频正在后台处理中，请稍候...</p>

        <div className="space-y-2">
          <div className="w-full bg-gray-800 rounded-full h-2.5">
            <div className="bg-gradient-to-r from-blue-500 to-purple-500 h-2.5 rounded-full transition-all duration-1000"
              style={{ width: `${progressPct}%` }} />
          </div>
          <div className="flex justify-between text-xs text-gray-600">
            <span>抽帧</span>
            <span>推理计算</span>
            <span>导出GLB</span>
            <span>完成</span>
          </div>
        </div>

        <Link to="/" className="text-blue-400 hover:underline text-sm mt-8 inline-block">上传新视频</Link>
      </div>
    );
  }

  if (job.status === 'failed') {
    return (
      <div className="max-w-lg mx-auto px-4 pt-24 text-center">
        <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-red-500/20 flex items-center justify-center">
          <span className="text-2xl">!</span>
        </div>
        <h2 className="text-xl font-semibold text-red-400 mb-2">处理失败</h2>
        <p className="text-gray-400 mb-4">{job.error_message || '未知错误'}</p>
        <Link to="/" className="text-blue-400 hover:underline">重新上传</Link>
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
