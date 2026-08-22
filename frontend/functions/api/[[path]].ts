/**
 * Proxy /api/* to the Lambda Function URL.
 *
 * Keeping the API on the same origin as the app removes CORS entirely — no
 * preflight, no allowed-origin list to keep in sync with deploy previews —
 * and keeps the Lambda URL out of the browser, so it cannot be called
 * directly or scraped from bundled JS.
 *
 * LAMBDA_URL is set in the Pages project's environment variables.
 */

interface Env {
  LAMBDA_URL: string;
}

export const onRequest: PagesFunction<Env> = async (context) => {
  const { request, env } = context;

  if (!env.LAMBDA_URL) {
    return Response.json(
      { error: "LAMBDA_URL이 설정되지 않았습니다", code: "NOT_CONFIGURED" },
      { status: 503 },
    );
  }

  const incoming = new URL(request.url);
  // /api/flood-risk -> <lambda>/flood-risk
  const path = incoming.pathname.replace(/^\/api/, "");
  const target = env.LAMBDA_URL.replace(/\/$/, "") + path + incoming.search;

  const response = await fetch(target, {
    method: request.method,
    headers: { "content-type": "application/json" },
    body: request.method === "GET" || request.method === "HEAD"
      ? undefined
      : await request.text(),
  });

  // Rebuild the response so upstream hop-by-hop headers are not forwarded.
  return new Response(response.body, {
    status: response.status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": response.headers.get("cache-control") ?? "no-store",
    },
  });
};
