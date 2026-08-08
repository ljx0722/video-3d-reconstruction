import { useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useDropzone } from 'react-dropzone';
import { createJob, uploadVideo } from '../api/client';

export default function UploadZone() {
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [fps, setFps] = useState(10);
  const navigate = useNavigate();

  const onDrop = useCallback(async (acceptedFiles: File[]) => {
    const file = acceptedFiles[0];
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const { id } = await uploadVideo(file, { fps, mode: 'streaming', conf_threshold: 1.5 }, (p) => setProgress(p));
      navigate(`/viewer/${id}`);
    } catch (e: any) {
      setError(e.message || 'Upload failed');
    } finally {
      setUploading(false);
      setProgress(0);
    }
  }, [fps, navigate]);

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
        <h1 className="text-3xl font-bold mb-2">Upload a video, get a 3D model</h1>
        <p className="text-gray-400">Free-browse point cloud reconstruction in your browser</p>
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
            <p className="text-lg mb-3">Uploading...</p>
            <div className="w-full bg-gray-800 rounded-full h-2">
              <div className="bg-blue-500 h-2 rounded-full transition-all" style={{ width: `${progress}%` }} />
            </div>
            <p className="text-sm text-gray-500 mt-2">{progress}%</p>
          </div>
        ) : (
          <div>
            <p className="text-lg mb-1">Drop a video here or click to browse</p>
            <p className="text-sm text-gray-500">MP4, MOV, AVI, MKV — up to 2GB</p>
          </div>
        )}
      </div>

      {error && <p className="text-red-400 text-sm mt-4 text-center">{error}</p>}

      <div className="mt-6 p-4 bg-gray-900 rounded-lg">
        <label className="text-sm text-gray-400">Extraction FPS: {fps}</label>
        <input type="range" min={1} max={30} value={fps} onChange={(e) => setFps(Number(e.target.value))}
          className="w-full mt-1 accent-blue-500" />
      </div>
    </div>
  );
}
