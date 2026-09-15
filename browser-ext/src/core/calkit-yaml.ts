import { HUBS, normalizeHubUrl } from "./hubs";

/**
 * The hub a calkit.yaml says its project belongs to.
 *
 * A project only names its hub when that hub isn't calkit.io, so an
 * absent key means calkit.io rather than "whichever hub the reader
 * happens to be using". This matches `ProjectInfo.hub` in the Python
 * package, where the field is likewise absent for calkit.io.
 *
 * Only that one top-level scalar is read, rather than pulling in a YAML
 * parser for a file nothing else here looks at.
 */
export function hubUrlFromCalkitYaml(text: string): string {
  // Quoted either way, or bare and running up to a trailing comment
  const match = text.match(
    /^hub:[ \t]*(?:"([^"]*)"|'([^']*)'|([^#\n]*?))[ \t]*(?:#.*)?$/m,
  );
  const declared = (match?.[1] ?? match?.[2] ?? match?.[3])?.trim();
  if (!declared) {
    return HUBS.production.webUrl;
  }
  return normalizeHubUrl(declared);
}
