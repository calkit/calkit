import { readFileSync, writeFileSync } from "node:fs";

// The manifest that goes to the Chrome Web Store, made from the one used
// for development.
//
// The local development hub is the only difference: reviewers see an
// http:// host permission that nothing in a published build can use, and
// every host permission is something they have to weigh. Loading unpacked
// keeps it, since that's where it's needed -- which is why this takes the
// path to a staged copy and never touches dist itself.
const path = process.argv[2];
if (!path) {
  throw new Error("Usage: node scripts/package-manifest.mjs <manifest path>");
}
const manifest = JSON.parse(readFileSync(path, "utf8"));
const before = manifest.host_permissions.length;
manifest.host_permissions = manifest.host_permissions.filter(
  (host) => !host.startsWith("http://"),
);
writeFileSync(path, JSON.stringify(manifest, null, 2) + "\n");
console.log(
  `host permissions: ${before} -> ${manifest.host_permissions.length}` +
    " (development hosts removed)",
);
