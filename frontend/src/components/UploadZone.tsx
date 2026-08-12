import { useState, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useDropzone } from 'react-dropzone';
import { uploadVideo } from '../api/client';

export default function UploadZone() {
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [uploadSpeed, setUploadSpeed] = useState<string>('');
  const [error, setError] = useState<string | null>(null);
  const [fps, setFps] = useState(10);
  const [confidencePercentile, setConfidencePercentile] = useState(5);
  const [totalMb, setTotalMb] = useState(0);
  const startTime = useRef(0);
  const navigate = useNavigate();

  const onDrop = useCallback(async (acceptedFiles: File[]) => {
    const file = acceptedFiles[0];
    if (!file) return;
    setUploading(true);
    setError(null);
    setTotalMb(Math.round(file.size / (1024 * 1024)));
    startTime.current = Date.now();
    try {
      const { id } = await uploadVideo(file, { fps, mode: 'streaming', conf_threshold: confidencePercentile }, (pct, loaded) => {
        setProgress(pct);
        if (loaded) {
          const elapsed = (Date.now() - startTime.current) / 1000;
          if (elapsed > 0 && pct < 100) {
            const speedMb = loaded / elapsed / (1024 * 1024);
            setUploadSpeed(speedMb < 1 ? `${(speedMb * 1024).toFixed(0)} KB/s` : `${speedMb.toFixed(1)} MB/s`);
          }
        }
      });
      navigate(`/viewer/${id}`);
    } catch (e: any) {
      setError(e.message || '上传失败，请重试');
    } finally {
      setUploading(false);
      setProgress(0);
      setUploadSpeed('');
    }
  }, [confidencePercentile, fps, navigate]);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { 'video/*': ['.mp4', '.mov', '.avi', '.mkv', '.webm'] },
    maxFiles: 1,
    maxSize: 2 * 1024 * 1024 * 1024,
    disabled: uploading,
  });

  return (
    <div className="max-w-2xl mx-auto px-4 pt-24 pb-12">
      <div className="text-center mb-8">
        <h1 className="text-3xl font-bold mb-2">三维世界实验室</h1>
        <p className="text-gray-400">上传视频，AI 自动生成可自由浏览的三维点云模型</p>
      </div>

      <div
        {...getRootProps()}
        className={`border-2 border-dashed rounded-xl p-12 text-center cursor-pointer transition-colors
          ${isDragActive ? 'border-blue-500 bg-blue-500/10' : 'border-gray-700 hover:border-gray-500'}
          ${uploading ? 'pointer-events-none opacity-50' : ''}`}
      >
        <input {...getInputProps()} />
        {uploading ? (
          <div>
            <p className="text-lg mb-3">正在上传... {totalMb > 0 && `(${totalMb} MB)`}</p>
            <div className="w-full bg-gray-800 rounded-full h-3 mb-2">
              <div className="bg-gradient-to-r from-blue-500 to-purple-500 h-3 rounded-full transition-all duration-300" style={{ width: `${progress}%` }} />
            </div>
            <p className="text-sm text-gray-400">
              {progress}% {uploadSpeed ? `· ${uploadSpeed}` : ''}
              {progress >= 100 ? ' · 正在保存...' : ''}
            </p>
          </div>
        ) : (
          <div>
            <p className="text-lg mb-1">拖放视频到此处，或点击浏览选择文件</p>
            <p className="text-sm text-gray-500">支持 MP4、MOV、AVI、MKV 格式，最大 2GB</p>
          </div>
        )}
      </div>

      {error && (
        <div className="mt-4 p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 text-sm text-center">
          {error}
        </div>
      )}

      <div className="mt-6 p-4 bg-gray-900 rounded-lg">
        <label className="text-sm text-gray-400">抽帧频率：每秒 {fps} 帧</label>
        <input type="range" min={1} max={30} value={fps} onChange={(e) => setFps(Number(e.target.value))}
          className="w-full mt-2 accent-blue-500" />
        <div className="flex justify-between text-xs text-gray-600 mt-1">
          <span>1 fps（快速/低精度）</span>
          <span>30 fps（慢速/高精度）</span>
        </div>
      </div>

      <div className="mt-3 p-4 bg-gray-900 rounded-lg">
        <label className="text-sm text-gray-400">丢弃最低置信度点：{confidencePercentile}%</label>
        <input type="range" min={0} max={20} step={1} value={confidencePercentile}
          onChange={(e) => setConfidencePercentile(Number(e.target.value))}
          className="w-full mt-2 accent-blue-500" />
        <div className="flex justify-between text-xs text-gray-600 mt-1">
          <span>0%（保留更多细节）</span>
          <span>20%（更强去噪）</span>
        </div>
      </div>
    </div>
  );
}
