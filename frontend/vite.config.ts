import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

/**
 * Dev-only proxy for `/api/*`.
 *
 * In production Cloudflare Pages Functions serve `/api/*` and forward to the
 * Lambda, so the app calls a same-origin path and never sees CORS. `vite dev`
 * does not run Pages Functions, so without this the same path 404s locally and
 * the app appears broken for reasons that have nothing to do with the code.
 *
 * Proxying in Vite rather than pointing the app at the Lambda directly keeps
 * dev and production on the identical relative path, and matters for a second
 * reason: the Function URL sends no CORS headers, so a browser calling it
 * straight from localhost is blocked outright. This proxy runs in Node, where
 * that restriction does not apply.
 *
 * LAMBDA_URL comes from `frontend/.env.local`, which is gitignored. It is read
 * here in the config rather than exposed as a `VITE_` variable so it stays out
 * of the client bundle -- `server` config is dev-only and is never built.
 */
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const lambdaUrl = env.LAMBDA_URL?.trim().replace(/\/$/, "");

  if (!lambdaUrl && mode === "development") {
    console.warn(
      "\n[waterpark] LAMBDA_URL이 없어 /api/* 프록시를 끕니다.\n" +
        "            frontend/.env.local 에 LAMBDA_URL=... 을 넣으세요.\n" +
        "            (frontend/.env.example 참고)\n",
    );
  }

  return {
    plugins: [react()],
    server: lambdaUrl
      ? {
          proxy: {
            "/api": {
              target: lambdaUrl,
              changeOrigin: true,
              // /api/flood-risk -> <lambda>/flood-risk, matching the
              // Pages Function's rewrite so both environments agree.
              rewrite: (path) => path.replace(/^\/api/, ""),
            },
          },
        }
      : undefined,
  };
});
