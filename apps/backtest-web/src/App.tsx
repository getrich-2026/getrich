import { Routes, Route, Link, useNavigate } from "react-router-dom";
import Dashboard from "./pages/Dashboard";
import Strategies from "./pages/Strategies";
import Signals from "./pages/Signals";
import Trades from "./pages/Trades";
import Login from "./pages/Login";
import Register from "./pages/Register";
import StrategyEdit from "./pages/StrategyEdit";
import StrategyDetail from "./pages/StrategyDetail";
import SignalDetail from "./pages/SignalDetail";
import Orders from "./pages/Orders";
import SignalSettings from "./pages/SignalSettings";
import BacktestJobs from "./pages/backtests/BacktestJobs";
import BacktestJobDetail from "./pages/backtests/BacktestJobDetail";
import BacktestRunDetail from "./pages/backtests/BacktestRunDetail";
import BacktestSweepDetail from "./pages/backtests/BacktestSweepDetail";
import BacktestWalkForwardDetail from "./pages/backtests/BacktestWalkForwardDetail";
import NewBacktestJob from "./pages/backtests/NewBacktestJob";
import NewSweepJob from "./pages/backtests/NewSweepJob";
import NewWalkForwardJob from "./pages/backtests/NewWalkForwardJob";
import ProtectedRoute from "./components/ProtectedRoute";
import PublicRoute from "./components/PublicRoute";
import { useAuth } from "./contexts/AuthContext";

function App() {
  const { isAuthenticated, user, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  return (
    <div className="app-shell">
      <nav className="app-nav">
        <Link to="/" className="nav-brand">
          GetRich
        </Link>
        <div className="nav-links">
          {isAuthenticated ? (
            <>
              <Link to="/">Dashboard</Link>
              <Link to="/strategies">Strategies</Link>
              <Link to="/signals">Signals</Link>
              <Link to="/trades">Trades</Link>
              <Link to="/backtests">Backtests</Link>
              <Link to="/orders">Orders</Link>
              <Link to="/settings">Settings</Link>
              {user && (
                <span className="text-muted" style={{ fontSize: 13, marginLeft: 8 }}>
                  {user.email}
                </span>
              )}
              <button
                onClick={handleLogout}
                style={{
                  padding: "4px 12px",
                  border: "1px solid var(--border)",
                  borderRadius: "var(--radius)",
                  background: "transparent",
                  color: "var(--danger)",
                  fontSize: 13,
                  cursor: "pointer",
                  marginLeft: 12,
                }}
              >
                Logout
              </button>
            </>
          ) : (
            <>
              <Link to="/login">Login</Link>
              <Link to="/register">Register</Link>
            </>
          )}
        </div>
      </nav>
      <main className="app-main">
        <Routes>
          <Route
            path="/"
            element={
              <ProtectedRoute>
                <Dashboard />
              </ProtectedRoute>
            }
          />
          <Route
            path="/strategies"
            element={
              <ProtectedRoute>
                <Strategies />
              </ProtectedRoute>
            }
          />
          <Route
            path="/signals"
            element={
              <ProtectedRoute>
                <Signals />
              </ProtectedRoute>
            }
          />
          <Route
            path="/signals/:code"
            element={
              <ProtectedRoute>
                <SignalDetail />
              </ProtectedRoute>
            }
          />
          <Route
            path="/trades"
            element={
              <ProtectedRoute>
                <Trades />
              </ProtectedRoute>
            }
          />
          <Route
            path="/strategies/:code/edit"
            element={
              <ProtectedRoute>
                <StrategyEdit />
              </ProtectedRoute>
            }
          />
          <Route
            path="/strategies/:code"
            element={
              <ProtectedRoute>
                <StrategyDetail />
              </ProtectedRoute>
            }
          />
          <Route
            path="/settings"
            element={
              <ProtectedRoute>
                <SignalSettings />
              </ProtectedRoute>
            }
          />
          <Route
            path="/backtests"
            element={
              <ProtectedRoute>
                <BacktestJobs />
              </ProtectedRoute>
            }
          />
          <Route
            path="/backtests/new"
            element={
              <ProtectedRoute>
                <NewBacktestJob />
              </ProtectedRoute>
            }
          />
          <Route
            path="/backtests/new-sweep"
            element={
              <ProtectedRoute>
                <NewSweepJob />
              </ProtectedRoute>
            }
          />
          <Route
            path="/backtests/new-walk-forward"
            element={
              <ProtectedRoute>
                <NewWalkForwardJob />
              </ProtectedRoute>
            }
          />
          <Route
            path="/backtests/:jobId"
            element={
              <ProtectedRoute>
                <BacktestJobDetail />
              </ProtectedRoute>
            }
          />
          <Route
            path="/backtest-runs/:runId"
            element={
              <ProtectedRoute>
                <BacktestRunDetail />
              </ProtectedRoute>
            }
          />
          <Route
            path="/backtest-sweeps/:sweepId"
            element={
              <ProtectedRoute>
                <BacktestSweepDetail />
              </ProtectedRoute>
            }
          />
          <Route
            path="/backtest-walk-forwards/:walkForwardId"
            element={
              <ProtectedRoute>
                <BacktestWalkForwardDetail />
              </ProtectedRoute>
            }
          />
          <Route
            path="/orders"
            element={
              <ProtectedRoute>
                <Orders />
              </ProtectedRoute>
            }
          />
          <Route
            path="/login"
            element={
              <PublicRoute>
                <Login />
              </PublicRoute>
            }
          />
          <Route
            path="/register"
            element={
              <PublicRoute>
                <Register />
              </PublicRoute>
            }
          />
        </Routes>
      </main>
    </div>
  );
}

export default App;
