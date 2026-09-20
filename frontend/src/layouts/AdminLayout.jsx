import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

export default function AdminLayout({ children }) {
  const auth = useAuth(); const nav = useNavigate();
  async function signOut() { await auth.logout(); nav('/'); }
  return <div className="admin-app"><header className="admin-topbar"><button className="wordmark" onClick={() => nav('/admin')}><span className="logo-heart">♥</span><span>Aarogya<span>Saar</span></span></button><div className="admin-context"><span className="admin-badge">HOSPITAL ADMIN</span><strong>{auth.user?.name}</strong><button className="btn btn-quiet" onClick={signOut}>Exit</button></div></header><main className="admin-main">{children}</main></div>;
}
