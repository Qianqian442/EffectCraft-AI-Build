/**
 * Basic local health endpoint for the EffectCraft EdgeOne relay project.
 */
export function onRequestGet(context) {
  return new Response(JSON.stringify({
    ok: true,
    service: "EffectCraft EdgeOne Relay",
    message: "Relay deployment is online. Use /api/_relay-health to check configuration.",
    region: context.server?.region ?? null,
  }), {
    status: 200,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
    },
  });
}
