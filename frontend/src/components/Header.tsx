import { Link, useLocation } from 'react-router-dom';

export default function Header() {
  const { pathname } = useLocation();

  return (
    <>
      <div className="bg-gray-900 border-b border-gray-800/50">
        <div className="max-w-7xl mx-auto px-4 h-7 flex items-center justify-center gap-3 text-[11px]">
          <span className="text-gray-400 tracking-wide">上海长晴人工智能科技有限公司</span>
          <span className="text-gray-700">|</span>
          <span className="text-gray-500 tracking-wide">Changqing AI Technology (Shanghai) Co., Ltd.</span>
        </div>
      </div>
      <header className="border-b border-gray-800 bg-gray-950/80 backdrop-blur sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 h-14 flex items-center justify-between">
          <Link to="/" className="flex items-center gap-3">
            <img src="/logo.svg" alt="3D World Lab" className="w-9 h-9" />
            <div className="flex items-baseline gap-2">
              <span className="text-sm font-bold tracking-tight">三维世界实验室</span>
              <span className="text-[10px] text-gray-500">3D World Lab</span>
            </div>
          </Link>
          <nav className="flex gap-6 text-sm">
            <Link to="/" className={pathname === '/' ? 'text-white' : 'text-gray-400 hover:text-white transition-colors'}>
              上传视频
            </Link>
            <Link to="/jobs" className={pathname === '/jobs' ? 'text-white' : 'text-gray-400 hover:text-white transition-colors'}>
              作业历史
            </Link>
          </nav>
        </div>
      </header>
    </>
  );
}
