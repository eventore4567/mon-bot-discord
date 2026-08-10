// Minimal SentriX Managed Runtime template for discord.js.
const fs = require('node:fs/promises');

async function waitForGatewayGate() {
  const gate = process.env.SENTRIX_GATE_FILE || '/run/sentrix/gateway.ready';
  for (;;) {
    try { await fs.access(gate); return; } catch (_) { await new Promise(r => setTimeout(r, 100)); }
  }
}

async function main() {
  await waitForGatewayGate();
  const tokenPath = process.env.SENTRIX_DISCORD_TOKEN_FILE || '/run/secrets/discord_token';
  const token = (await fs.readFile(tokenPath, 'utf8')).trim();
  if (!token) throw new Error('empty Discord token');
  console.log('SentriX managed runtime gate opened; user bot may connect');
  // Create Client and call login(token) in the application-specific template.
}

main().catch(err => { console.error(err); process.exitCode = 1; });
