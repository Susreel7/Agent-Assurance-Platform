/**
 * The provider's redirect lands here.
 *
 * One job: hand the authorization code to `POST /v1/auth/session` and navigate **only**
 * on success. A failure stays on this screen with the server's reason on it, because the
 * previous behaviour — navigate first, discover the onboarding failed later — is exactly
 * how the console came to have a session with no member behind it.
 *
 * The browser never sees a token. The server exchanges the code, verifies the id token,
 * resolves the member and sets an `HttpOnly` cookie, all before this screen is told
 * anything.
 */

import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { ReasonState } from "@/components/DataBoundary";
import { BOOTSTRAP_KEY } from "./useBootstrap";
import { completeLogin, forgetPendingLogin } from "./session";
import { LoginFrame } from "./LoginScreen";

export default function LoginCallbackScreen() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [params] = useSearchParams();
  const [failure, setFailure] = useState<unknown>(null);
  // An authorization code is single-use. React 18 mounts effects twice in development,
  // and without this the second attempt redeems a code the first already spent — which
  // the provider correctly refuses, so a working sign-in reports `invalid_credential`.
  const attempted = useRef(false);

  useEffect(() => {
    if (attempted.current) return;
    attempted.current = true;

    void (async () => {
      try {
        const { returnTo } = await completeLogin(params);
        // The session is new, so anything cached under the previous one is wrong.
        queryClient.removeQueries({ queryKey: BOOTSTRAP_KEY });
        navigate(returnTo, { replace: true });
      } catch (err) {
        forgetPendingLogin();
        setFailure(err);
      }
    })();
  }, [navigate, params, queryClient]);

  if (failure) {
    return (
      <LoginFrame subtitle="Sign-in did not complete">
        <ReasonState error={failure} />
        <button
          type="button"
          className="glass-button-primary mt-4 w-full rounded-xl px-4 py-3 text-sm font-bold"
          onClick={() => navigate("/login", { replace: true })}
        >
          Back to sign-in
        </button>
      </LoginFrame>
    );
  }

  return (
    <LoginFrame subtitle="Completing sign-in">
      <div className="flex items-center gap-3 text-xs font-semibold text-slate-500">
        <span className="h-2 w-2 animate-pulse rounded-full bg-emerald-400" />
        Verifying with your identity provider…
      </div>
    </LoginFrame>
  );
}
