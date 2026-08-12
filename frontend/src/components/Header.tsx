import { useEffect, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { formatBeijingDateTime } from '../time';

export default function Header() {
  const { pathname } = useLocation();
  const [beijingTime, setBeijingTime] = useState(() => formatBeijingDateTime(new Date()));

  useEffect(() => {
    const updateTime = () => setBeijingTime(formatBeijingDateTime(new Date()));
    const timer = window.setInterval(updateTime, 1000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <header className="border-b border-gray-800 bg-gray-950/80 backdrop-blur sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-4 min-h-12 py-1.5 flex items-center justify-between gap-4">
        <div className="flex items-center gap-3 min-w-0">
          <Link to="/" className="flex items-center gap-2 flex-shrink-0">
            <img src="/logo.svg" alt="3D World Lab" className="w-7 h-7" />
            <span className="text-xs font-bold tracking-tight">三维世界实验室</span>
            <span className="text-[9px] text-gray-500 hidden sm:inline">3D World Lab</span>
          </Link>
          <span className="text-gray-700 text-xs">|</span>
          <div className="hidden md:flex min-w-0 flex-col text-[9px] leading-4 text-gray-500">
            <span className="truncate">上海长晴人工智能科技有限公司 · Changqing AI Technology (Shanghai) Co., Ltd.</span>
            <span className="truncate text-gray-400">产品开发：长晴科技 Liujinxiu · 系统时间（北京时间）：{beijingTime}</span>
          </div>
        </div>
        <nav className="flex gap-4 text-xs flex-shrink-0 ml-4">
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
