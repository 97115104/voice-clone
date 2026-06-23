#!/usr/bin/env node
/**
 * Creates an attestation for voice-clone via attest-client.
 * Run: npm run attest
 * Writes web/attestation.json for the footer.
 */
import { attest } from "attest-client";
import { writeFileSync } from "fs";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));

try {
  const result = await attest({
    content_name: "voice-clone",
    model: "composer",
    role: "collaborated",
    author: "97115104",
    platform: "Cursor",
  });

  const data = {
    shortUrl: result.urls.short,
    verifyUrl: result.urls.verify,
    id: result.attestation.id,
    timestamp: result.attestation.timestamp,
    model: result.attestation.model,
    platform: result.attestation.platform,
  };

  const outPath = resolve(__dirname, "../web/attestation.json");
  writeFileSync(outPath, JSON.stringify(data, null, 2) + "\n");
  console.log("Attestation created:", data.shortUrl);
} catch (err) {
  console.error("Attestation failed:", err.message);
  process.exit(1);
}
