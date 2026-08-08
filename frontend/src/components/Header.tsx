import { Link, useLocation } from 'react-router-dom';

export default function Header() {
  const { pathname } = useLocation();

  return (
    <header className="border-b border-gray-800 bg-gray-950/80 backdrop-blur sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-4 h-14 flex items-center justify-between">
        <Link to="/" className="flex items-center gap-2 text-lg font-semibold tracking-tight">
          <span className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center text-sm font-bold">3D</span>
          Video2Gauss
        </Link>
        <nav className="flex gap-6 text-sm">
          <Link to="/" className={pathname === '/' ? 'text-white' : 'text-gray-400 hover:text-white transition-colors'}>
            Upload
          </Link>
          <Link to="/jobs" className={pathname === '/jobs' ? 'text-white' : 'text-gray-400 hover:text-white transition-colors'}>
            Jobs
          </Link>
        </nav>
      </div>
    </header>
  );
}
