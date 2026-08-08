import { useParams, Link } from 'react-router-dom';
import useSWR from 'swr';
import { getJob } from '../api/client';
import ViewerCanvas from './ViewerCanvas';
import type { Job } from '../types';

const statusSteps = [
  { key: 'uploading', label: '上传视频', icon: '↑' },
  { key: 'uploaded', label: '已上传，等待处理', icon: '✓' },
  { key: 'processing', label: 'GPU 推理计算中', icon: '⚙' },
  { key: 'exporting', label: '导出 3D 模型', icon: '◈' },
  { key: 'completed', label: '重建完成', icon: '✓' },
];

export default function ViewerPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const { data: job, error } = useSWR<Job>(
    jobId ? `job-${jobId}` : null,
    () => getJob(jobId!),
    { refreshInterval: 2000 }
  );

  if (error) return <p className="text-center text-red-400 mt-12">加载作业失败</p>;
  if (!job) return (
    <div className="flex items-center justify-center h-full">
      <div className="w-12 h-12 border-4 border-blue-500 border-t-transparent rounded-full animate-spin" />
    </div>
  );

  const isProcessing = job.status === 'uploaded' || job.status === 'processing';
  const progressPct = Math.max(2, Math.min(100, (job.progress || 0) * 100));

  const currentStep = job.status === 'completed' ? 4
    : job.progress >= 0.8 ? 3
    : job.progress >= 0.15 ? 2
    : job.status === 'processing' ? 2
    : 1;

  const videoUrl = jobId ? `/api/v1/gpu/video/${jobId}` : '';

  return (
    <div className="h-[calc(100vh-7.5rem)] flex">
      {/* Left Panel */}
      <div className="w-72 flex-shrink-0 border-r border-gray-800 bg-gray-950 flex flex-col overflow-hidden">
        {/* Video Player */}
        {videoUrl && (
          <div className="p-3 border-b border-gray-800">
            <div className="text-xs text-gray-500 mb-2">原始视频</div>
            <video
              src={videoUrl}
              controls
              className="w-full rounded-lg bg-black"
              style={{ maxHeight: '180px' }}
              preload="metadata"
            />
          </div>
        )}

        {/* Processing Steps */}
        <div className="p-3 flex-1 overflow-auto">
          <div className="text-xs text-gray-500 mb-3">处理进度</div>

          {isProcessing ? (
            <div className="mb-4">
              <div className="flex items-center gap-3 mb-2">
                <div className="relative w-12 h-12 flex-shrink-0">
                  <svg className="w-12 h-12 -rotate-90" viewBox="0 0 48 48">
                    <circle cx="24" cy="24" r="20" fill="none" stroke="#1f2937" strokeWidth="3" />
                    <circle cx="24" cy="24" r="20" fill="none" stroke="url(#pg)" strokeWidth="3" strokeLinecap="round"
                      strokeDasharray={`${1.25 * progressPct} ${125 - 1.25 * progressPct}`} />
                    <defs>
                      <linearGradient id="pg" x1="0" y1="0" x2="1" y2="1">
                        <stop offset="0%" stopColor="#3B82F6" />
                        <stop offset="100%" stopColor="#8B5CF6" />
                      </linearGradient>
                    </defs>
                  </svg>
                  <span className="absolute inset-0 flex items-center justify-center text-xs font-bold">
                    {Math.round(progressPct)}%
                  </span>
                </div>
                <div>
                  <div className="text-sm font-medium">
                    {job.status === 'processing' ? '推理计算中...' : '等待处理...'}
                  </div>
                  <div className="text-xs text-gray-500">
                    {job.num_frames ? `${job.num_frames} 帧` : '准备中'}
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <div className="mb-4 text-sm text-green-400 flex items-center gap-2">
              <span className="text-lg">&#x2713;</span> 处理完成
            </div>
          )}

          {/* Steps list */}
          <div className="space-y-1">
            {statusSteps.map((step, i) => {
              const isActive = i === currentStep;
              const isDone = i < currentStep;
              return (
                <div key={step.key} className={`flex items-center gap-2 py-1 px-2 rounded text-xs ${
                  isActive ? 'bg-blue-500/10 text-blue-400' :
                  isDone ? 'text-green-400/70' : 'text-gray-600'
                }`}>
                  <span className="w-4 text-center">{isDone ? '✓' : isActive ? '●' : '○'}</span>
                  <span>{step.label}</span>
                </div>
              );
            })}
          </div>

          {/* Job Info */}
          {job.status === 'completed' && (
            <div className="mt-4 pt-3 border-t border-gray-800 text-xs text-gray-500 space-y-1">
              {job.num_frames && <p>总帧数：{job.num_frames}</p>}
              {job.num_points && <p>点云数量：{(job.num_points / 10000).toFixed(1)} 万</p>}
              {job.processing_time_secs && <p>处理耗时：{job.processing_time_secs.toFixed(1)} 秒</p>}
            </div>
          )}

          {/* Error */}
          {job.status === 'failed' && (
            <div className="mt-3 p-2 bg-red-500/10 border border-red-500/20 rounded text-xs text-red-400">
              处理失败: {job.error_message || '未知错误'}
            </div>
          )}
        </div>

        {/* Actions */}
        <div className="p-3 border-t border-gray-800 flex gap-2">
          <Link to="/" className="flex-1 text-center py-1.5 rounded bg-gray-800 hover:bg-gray-700 text-xs text-gray-300 transition-colors">
            上传新视频
          </Link>
          <Link to="/jobs" className="flex-1 text-center py-1.5 rounded bg-gray-800 hover:bg-gray-700 text-xs text-gray-300 transition-colors">
            作业历史
          </Link>
        </div>
      </div>

      {/* Main 3D Viewer */}
      <div className="flex-1 relative bg-black">
        {job.status === 'completed' ? (
          <ViewerCanvas jobId={job.id} />
        ) : job.status === 'failed' ? (
          <div className="absolute inset-0 flex items-center justify-center text-gray-500">
            <div className="text-center">
              <div className="text-4xl mb-3">!</div>
              <p>处理失败</p>
              <p className="text-xs mt-1">{job.error_message?.slice(0, 100)}</p>
            </div>
          </div>
        ) : (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="text-center">
              <div className="w-16 h-16 mx-auto mb-4 border-4 border-blue-500 border-t-transparent rounded-full animate-spin" />
              <p className="text-gray-400 text-sm">正在重建三维模型...</p>
              <p className="text-gray-600 text-xs mt-1">这通常需要 1-3 分钟</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
