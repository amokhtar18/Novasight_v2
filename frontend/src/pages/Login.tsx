/**
 * Login — the password sign-in screen.
 *
 * Posts credentials to /auth/login; on success the session is recorded in the
 * auth store (by `useLogin`) and the user is sent to where they were headed (or
 * the overview). Already-authenticated visitors are redirected away.
 *
 * The "Workspace" (tenant slug) field is optional — omitted, the backend uses the
 * seed tenant, which is the common single-tenant case.
 */

import { useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import { useLogin } from "@/api/hooks";
import { useAuthStore } from "@/store/authStore";
import { BrandMark } from "@/components/BrandMark";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

interface LocationState {
  from?: { pathname: string };
}

export function Login() {
  const navigate = useNavigate();
  const location = useLocation();
  const authed = useAuthStore((s) => s.accessToken !== null);
  const loginMutation = useLogin();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [tenant, setTenant] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(false);

  const from = (location.state as LocationState | null)?.from?.pathname ?? "/";

  if (authed) {
    return <Navigate to={from} replace />;
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    loginMutation.mutate(
      {
        email: email.trim(),
        password,
        tenant: tenant.trim() || undefined,
      },
      { onSuccess: () => navigate(from, { replace: true }) }
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex flex-col items-center gap-2 text-center">
          <BrandMark className="h-9" />
          <h1 className="text-xl font-semibold tracking-tight">NovaSight</h1>
          <p className="text-sm text-muted-foreground">
            Sign in to your analytics workspace
          </p>
        </div>

        <Card className="bg-card/80">
          <CardContent className="pt-6">
            <form onSubmit={handleSubmit} className="space-y-4">
              {loginMutation.isError && (
                <Alert variant="destructive">
                  <AlertTitle>Sign-in failed</AlertTitle>
                  <AlertDescription>
                    {loginMutation.error instanceof Error
                      ? loginMutation.error.message
                      : "Check your credentials and try again."}
                  </AlertDescription>
                </Alert>
              )}

              <div className="space-y-1.5">
                <Label htmlFor="login-email">Email</Label>
                <Input
                  id="login-email"
                  type="email"
                  autoComplete="username"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@example.com"
                  required
                  autoFocus
                />
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="login-password">Password</Label>
                <Input
                  id="login-password"
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  required
                />
              </div>

              {showAdvanced ? (
                <div className="space-y-1.5">
                  <Label htmlFor="login-tenant">Workspace</Label>
                  <Input
                    id="login-tenant"
                    value={tenant}
                    onChange={(e) => setTenant(e.target.value)}
                    placeholder="(default workspace)"
                  />
                </div>
              ) : (
                <button
                  type="button"
                  onClick={() => setShowAdvanced(true)}
                  className="text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
                >
                  Use a different workspace
                </button>
              )}

              <Button
                type="submit"
                className="w-full"
                disabled={loginMutation.isPending || !email.trim() || !password}
              >
                {loginMutation.isPending ? "Signing in…" : "Sign in"}
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
