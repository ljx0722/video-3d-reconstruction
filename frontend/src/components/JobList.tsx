import useSWR from 'swr';
import { Link } from 'react-router-dom';
import { listJobs, deleteJob } from '../api/client';
import { useState } from 'react';
import type { Job } from '../types';

const statusMap: Record<string, string> = {
  uploaded: '已上传',
  queued: '排队中',
  processing: '处理中',
  partial: '部分完成',
  completed: '已完成',
  failed: '失败',
};

const statusColors: Record<string, string> = {
  uploaded: 'bg-yellow-500/20 text-yellow-400',
  queued: 'bg-blue-500/20 text-blue-400',
  processing: 'bg-purple-500/20 text-purple-400',
  partial: 'bg-amber-500/20 text-amber-400',
  completed: 'bg-green-500/20 text-green-400',
  failed: 'bg-red-500/20 text-red-400',
};

function formatBeijingTime(iso: string | null | undefined) {
  if (!iso) return '';
  try { return new Date(iso).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }); }
  catch { return iso; }
}

function formatFileSize(bytes: number | null | undefined) {
  if (!bytes || bytes < 0) return '';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function JobList() {
  const { data: jobs, error, mutate } = useSWR<Job[]>('jobs', listJobs, { refreshInterval: 3000 });
  const [deleting, setDeleting] = useState<string | null>(null);

  const handleDelete = async (e: React.MouseEvent, jobId: string) => {
    e.preventDefault();
    e.stopPropagation();
    if (!confirm('确定要删除这个作业吗？关联的视频和模型文件也会被永久删除。')) return;
    setDeleting(jobId);
    try {
      await deleteJob(jobId);
      mutate((list) => list?.filter((j) => j.id !== jobId), false);
    } catch {
      alert('删除失败');
    } finally {
      setDeleting(null);
    }
  };

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
          <div key={job.id} className="relative group">
            <Link to={`/viewer/${job.id}`}
              className="block p-4 bg-gray-900 rounded-lg hover:bg-gray-800 transition-colors pr-20">
              <div className="flex items-center justify-between">
                <span className="font-mono text-sm text-gray-400">{job.id.slice(0, 8)}...</span>
                <span className={`text-xs px-2 py-0.5 rounded-full ${statusColors[job.status] || 'bg-gray-700'}`}>
                  {statusMap[job.status] || job.status}
                </span>
              </div>
              <div className="text-xs text-gray-500 mt-2 space-y-0.5">
                {job.file_name && <p>文件：<span className="text-gray-400">{job.file_name}</span></p>}
                <p>
                  {formatBeijingTime(job.created_at)}
                  {job.file_size_bytes && ` · ${formatFileSize(job.file_size_bytes)}`}
                  {job.num_points ? ` · ${(job.num_points / 10000).toFixed(1)} 万点` : ''}
                  {job.processing_time_secs && ` · 耗时 ${job.processing_time_secs.toFixed(0)}s`}
                </p>
              </div>
            </Link>
            <button
              onClick={(e) => handleDelete(e, job.id)}
              disabled={deleting === job.id}
              className="absolute right-3 top-1/2 -translate-y-1/2 px-3 py-1.5 rounded-md text-xs
                bg-red-500/10 text-red-400 hover:bg-red-500/20 hover:text-red-300
                opacity-0 group-hover:opacity-100 transition-all
                disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {deleting === job.id ? '删除中...' : '删除'}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
