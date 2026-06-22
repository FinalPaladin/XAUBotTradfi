const BLOCK_SECONDS = 30;

async function sha256Hex(input: string): Promise<string> {
  const data = new TextEncoder().encode(input);
  const hash = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(hash))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

async function secureKeyForBlock(secret: string, block: number): Promise<string> {
  const material = `${secret}:${block}`;
  return sha256Hex(material);
}

/** Generate X-Secure-Key for the current 30-second block. */
let _cached: { block: number; key: string } | null = null;

export async function generateSecureKeyAsync(): Promise<string> {
  const secret =
    import.meta.env.VITE_SECRET_KEY_DYNAMIC ?? "xaubot-secure-key-dynamic-dev";
  const block =
    Math.floor(Date.now() / 1000 / BLOCK_SECONDS) * BLOCK_SECONDS;
  if (_cached && _cached.block === block) {
    return _cached.key;
  }
  const key = await secureKeyForBlock(secret, block);
  _cached = { block, key };
  return key;
}

export async function warmSecureKey(): Promise<void> {
  await generateSecureKeyAsync();
}
