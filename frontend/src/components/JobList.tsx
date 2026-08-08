import useSWR from 'swr';
import { Link } from 'react-router-dom';
import { listJobs } from '../api/client';
import type { Job } from '../types';

const statusMap: Record<string, string> = {
  uploaded: '已上传',
  queued: '排队中',
  processing: '处理中',
  completed: '已完成',
  failed: '失败',
};

const statusColors: Record<string, string> = {
  uploaded: 'bg-yellow-500/20 text-yellow-400',
  queued: 'bg-blue-500/20 text-blue-400',
  processing: 'bg-purple-500/20 text-purple-400',
  completed: 'bg-green-500/20 text-green-400',
  failed: 'bg-red-500/20 text-red-400',
};

export default function JobList() {
  const { data: jobs, error } = useSWR<Job[]>('jobs', listJobs, { refreshInterval: 3000 });

  if (error) return <p className="text-center text-red-400 mt-12">加载失败</p>;
  if (!jobs) return <p className="text-center text-gray-500 mt-12">加载中...</p>;
  if (jobs.length === 0) {
    return (
      <div className="max-w-2xl mx-auto px-4 pt-24 text-center">
        <p className="text-gray-500 text-lg">暂无作业</p>
        <Link to="/" className="text-blue-400 hover:underline mt-2 inline-block">去上传视频</Link>
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto px-4 pt-8">
      <h2 className="text-xl font-semibold mb-4">作业历史</h2>
      <div className="space-y-3">
        {jobs.map((job) => (
          <Link key={job.id} to={`/viewer/${job.id}`}
            className="block p-4 bg-gray-900 rounded-lg hover:bg-gray-800 transition-colors">
            <div className="flex items-center justify-between">
              <span className="font-mono text-sm text-gray-400">{job.id.slice(0, 8)}...</span>
              <span className={`text-xs px-2 py-0.5 rounded-full ${statusColors[job.status] || 'bg-gray-700'}`}>
                {statusMap[job.status] || job.status}
              </span>
            </div>
            <div className="text-xs text-gray-500 mt-2">
              {new Date(job.created_at).toLocaleString('zh-CN')}
              {job.processing_time_secs && ` · 处理耗时 ${job.processing_time_secs.toFixed(1)} 秒`}
              {job.num_points && ` · ${(job.num_points / 10000).toFixed(0)} 万点`}
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
