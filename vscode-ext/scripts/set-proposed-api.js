const fs = require("node:fs");
const path = require("node:path");

const mode = process.argv[2];
if (mode !== "on" && mode !== "off") {
  console.error("Usage: node scripts/set-proposed-api.js <on|off>");
  process.exit(1);
}

const packagePath = path.join(__dirname, "..", "package.json");
const raw = fs.readFileSync(packagePath, "utf8");
const pkg = JSON.parse(raw);

if (mode === "on") {
  pkg.enabledApiProposals = ["notebookKernelSource"];
} else {
  delete pkg.enabledApiProposals;
}

fs.writeFileSync(packagePath, `${JSON.stringify(pkg, null, 2)}\n`, "utf8");
console.log(
  mode === "on"
    ? "Enabled proposed API: notebookKernelSource"
    : "Disabled proposed API declarations for publish",
);
