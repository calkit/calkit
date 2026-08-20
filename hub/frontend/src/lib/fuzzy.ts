// Subsequence matching for type-to-filter lists.
//
// People remember fragments of a name, not its exact spelling, so "navwake"
// should find "navier-wake-analysis" and "dtrawcsv" should find
// "data/raw/measurements.csv". A substring match would make them get the
// gaps right, which is the thing they can't do from memory.

/**
 * Score how well `text` matches `query`, or null if it doesn't.
 *
 * Lower is better: the score is the number of characters skipped over,
 * plus how far in the first match starts. So a tight match near the front
 * beats a scattered one further along.
 */
export function fuzzyScore(text: string, query: string): number | null {
  const target = text.toLowerCase()
  const q = query.toLowerCase().replace(/\s+/g, "")
  if (!q) return 0
  let score = 0
  let index = -1
  for (const char of q) {
    const next = target.indexOf(char, index + 1)
    if (next === -1) return null
    // A jump means characters the user didn't type; the further the jump,
    // the weaker the match. Consecutive characters cost nothing.
    score += next - index - 1
    index = next
  }
  return score + target.indexOf(q[0])
}

/**
 * Keep what matches, best first, capped at `limit`.
 *
 * Ties keep their original order, so a caller that sorted its items
 * meaningfully (most recent repo, shallowest path) keeps that ordering
 * among equally good matches.
 */
export function fuzzyFilter<T>(
  items: T[],
  query: string,
  getText: (item: T) => string,
  limit = 8,
): T[] {
  const scored: { item: T; score: number; index: number }[] = []
  items.forEach((item, index) => {
    const score = fuzzyScore(getText(item), query)
    if (score !== null) {
      scored.push({ item, score, index })
    }
  })
  scored.sort((a, b) => a.score - b.score || a.index - b.index)
  return scored.slice(0, limit).map((s) => s.item)
}
