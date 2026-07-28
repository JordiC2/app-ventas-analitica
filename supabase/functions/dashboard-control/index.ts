import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...corsHeaders, "Content-Type": "application/json; charset=utf-8" },
  });
}

function requiredEnv(name: string): string {
  const value = Deno.env.get(name)?.trim();
  if (!value) throw new Error(`Falta el secreto ${name}`);
  return value;
}

async function authenticatedUser(req: Request) {
  const authorization = req.headers.get("Authorization");
  if (!authorization?.startsWith("Bearer ")) return null;

  const supabase = createClient(
    requiredEnv("SUPABASE_URL"),
    requiredEnv("SUPABASE_ANON_KEY"),
    { global: { headers: { Authorization: authorization } } },
  );

  const { data, error } = await supabase.auth.getUser();
  if (error || !data.user) return null;
  return data.user;
}

async function dispatchWorkflow(requestedBy: string): Promise<void> {
  const owner = Deno.env.get("GITHUB_OWNER")?.trim() || "JordiC2";
  const repo = Deno.env.get("GITHUB_REPO")?.trim() || "app-ventas-analitica";
  const workflow = Deno.env.get("GITHUB_WORKFLOW")?.trim() || "sync-nightly.yml";
  const branch = Deno.env.get("GITHUB_BRANCH")?.trim() || "main";
  const token = requiredEnv("GITHUB_ACTIONS_TOKEN");

  const endpoint = `https://api.github.com/repos/${owner}/${repo}/actions/workflows/${workflow}/dispatches`;
  const response = await fetch(endpoint, {
    method: "POST",
    headers: {
      "Accept": "application/vnd.github+json",
      "Authorization": `Bearer ${token}`,
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "electro-ponent-dashboard-control",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      ref: branch,
      inputs: {
        force: "false",
        requested_by: requestedBy.slice(0, 120),
      },
    }),
  });

  if (response.status !== 204) {
    const detail = await response.text();
    throw new Error(`GitHub ha respondido ${response.status}: ${detail.slice(0, 500)}`);
  }
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  try {
    const user = await authenticatedUser(req);
    if (!user) return json({ error: "Sesión no válida" }, 401);

    if (req.method === "GET") {
      const formUrl = requiredEnv("VENTAS_FORM_URL");
      return json({
        form_url: formUrl,
        user: {
          id: user.id,
          email: user.email,
          nombre: user.user_metadata?.nombre ?? null,
        },
      });
    }

    if (req.method === "POST") {
      const body = await req.json().catch(() => ({}));
      if (body?.action !== "sync") {
        return json({ error: "Acción no reconocida" }, 400);
      }

      const requestedBy = user.email || user.id;
      await dispatchWorkflow(requestedBy);

      return json({
        accepted: true,
        message: "Sincronización solicitada. Los datos se actualizarán en unos instantes.",
        requested_at: new Date().toISOString(),
      }, 202);
    }

    return json({ error: "Método no permitido" }, 405);
  } catch (error) {
    console.error(error);
    return json({
      error: "No se ha podido completar la operación",
      detail: error instanceof Error ? error.message : String(error),
    }, 500);
  }
});
