// The dashboard's Cloudflare Worker. Pages and files are served straight from
// the static assets (wrangler.toml [assets]); this script adds one thing: a
// once-a-minute clock for dose reminders.
//
// The backend runs on a free Render service that sleeps when idle, so it
// cannot keep time itself. Every minute this asks it to send any reminders
// now due (POST /internal/reminders/tick), which also wakes it. The shared
// secret is a Worker secret: `npx wrangler secret put REMINDER_TICK_SECRET`.

export default {
  async fetch(request, env) {
    return env.ASSETS.fetch(request)
  },

  async scheduled(_controller, env, ctx) {
    if (!env.REMINDER_TICK_SECRET || !env.BACKEND_URL) return
    ctx.waitUntil(
      fetch(`${env.BACKEND_URL}/internal/reminders/tick`, {
        method: 'POST',
        headers: { 'X-Tick-Secret': env.REMINDER_TICK_SECRET },
      }).catch(() => undefined),
    )
  },
}
