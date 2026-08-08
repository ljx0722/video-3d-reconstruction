import { Link, useLocation } from 'react-router-dom';

export default function Header() {
  const { pathname } = useLocation();

  return (
    <header className="border-b border-gray-800 bg-gray-950/80 backdrop-blur sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-4 h-14 flex items-center justify-between">
        <Link to="/" className="flex items-center gap-3">
          <img src="/logo.svg" alt="3D World Lab" className="w-9 h-9" />
          <div className="flex flex-col leading-none">
            <div className="flex items-baseline gap-2">
              <span className="text-sm font-bold tracking-tight">三维世界实验室</span>
              <span className="text-[10px] text-gray-500">3D World Lab</span>
            </div>
            <span className="text-[10px] text-gray-500 tracking-wider">元智能 · Meta Intelligence</span>
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
  );
}
