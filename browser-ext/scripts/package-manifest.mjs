import { readFileSync, writeFileSync } from "node:fs";

// The manifest that goes to the Chrome Web Store, made from the one used
// for development.
//
// The development hubs are the difference: local and staging are reachable
// only by people working on Calkit itself (staging is hidden from the hub
// picker for everyone else), so a published build asking for them is a
// permission a reviewer has to weigh and nobody gets to use. Loading
// unpacked keeps them, which is why this takes the path to a staged copy
// and never touches dist itself.
const path = process.argv[2];
if (!path) {
  throw new Error("Usage: node scripts/package-manifest.mjs <manifest path>");
}
const manifest = JSON.parse(readFileSync(path, "utf8"));
const before = manifest.host_permissions.length;
const developmentOnly = (host) =>
  host.startsWith("http://") || host.includes("staging.");
manifest.host_permissions = manifest.host_permissions.filter(
  (host) => !developmentOnly(host),
);
writeFileSync(path, JSON.stringify(manifest, null, 2) + "\n");
console.log(
  `host permissions: ${before} -> ${manifest.host_permissions.length}` +
    " (development hosts removed)",
);
