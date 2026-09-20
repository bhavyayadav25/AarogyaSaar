import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { Loading } from './States';
export default function ProtectedRoute({ role }) {
  const auth = useAuth(); const location = useLocation();
  if (!auth.ready) return <Loading label="Preparing your secure session…" />;
  if (!auth.token) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  if (role && auth.user?.role !== role) return <Navigate to={auth.user?.role === 'doctor' ? '/doctor' : auth.user?.role === 'admin' ? '/admin' : '/patient'} replace />;
  return <Outlet />;
}
