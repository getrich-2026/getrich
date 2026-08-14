import {
  createContext,
  useContext,
  useState,
  useCallback,
  type ReactNode,
} from "react";
import type { UserInfo } from "../api/auth";
import {
  getAccessToken,
  setAccessToken,
  clearAccessToken,
  getStoredUser,
  setStoredUser,
  clearStoredUser,
  setRefreshToken,
  clearRefreshToken,
} from "../api/client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface AuthState {
  user: UserInfo | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (
    accessToken: string,
    user: UserInfo,
    refreshToken?: string,
  ) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthState | undefined>(undefined);
// Re-exported so tests (and any future test-only wrappers) can inject
// a stub AuthState directly. The real `AuthProvider` is the only
// production code path that should write to this context; consumers
// should call `useAuth()` instead of consuming the context by hand.
export { AuthContext };

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserInfo | null>(() => getStoredUser());
  const [isAuthenticated, setIsAuthenticated] = useState(
    () => !!getAccessToken(),
  );
  const [isLoading] = useState(false);

  const login = useCallback(
    (accessToken: string, newUser: UserInfo, refreshToken?: string) => {
      setAccessToken(accessToken);
      setStoredUser(newUser);
      if (refreshToken) {
        setRefreshToken(refreshToken);
      }
      setUser(newUser);
      setIsAuthenticated(true);
    },
    [],
  );

  const logout = useCallback(() => {
    clearAccessToken();
    clearRefreshToken();
    clearStoredUser();
    setUser(null);
    setIsAuthenticated(false);
  }, []);

  return (
    <AuthContext.Provider value={{ user, isAuthenticated, isLoading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return ctx;
}
