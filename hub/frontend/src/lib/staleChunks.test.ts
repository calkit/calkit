import { beforeEach, describe, expect, it, vi } from "vitest"

import { type ReloadTarget, reloadOnStaleChunk } from "./staleChunks"

interface Harness {
  target: ReloadTarget
  fire: () => { defaultPrevented: boolean }
  reload: ReturnType<typeof vi.fn>
}

function harness(storage?: ReloadTarget["sessionStorage"]): Harness {
  const items = new Map<string, string>()
  let listener: ((event: VitePreloadErrorEvent) => void) | undefined
  const reload = vi.fn()
  const target: ReloadTarget = {
    addEventListener: (_type, handler) => {
      listener = handler
    },
    sessionStorage: storage ?? {
      getItem: (key) => items.get(key) ?? null,
      setItem: (key, value) => {
        items.set(key, value)
      },
    },
    location: { reload },
  }
  reloadOnStaleChunk(target)
  return {
    target,
    reload,
    fire: () => {
      let defaultPrevented = false
      listener?.({
        preventDefault: () => {
          defaultPrevented = true
        },
      } as VitePreloadErrorEvent)
      return { defaultPrevented }
    },
  }
}

describe("reloadOnStaleChunk", () => {
  beforeEach(() => {
    vi.useRealTimers()
  })

  it("reloads on the first missing chunk and swallows the error", () => {
    const { fire, reload } = harness()
    expect(fire().defaultPrevented).toBe(true)
    expect(reload).toHaveBeenCalledOnce()
  })

  it("reloads once, not in a loop, when the chunk is really gone", () => {
    const { fire, reload } = harness()
    fire()
    // The reload didn't help, so the second failure has to surface rather
    // than reload again
    expect(fire().defaultPrevented).toBe(false)
    expect(reload).toHaveBeenCalledOnce()
  })

  it("reloads again once the cooldown has passed", () => {
    vi.useFakeTimers()
    const { fire, reload } = harness()
    fire()
    // A tab open long enough to see a second deploy should still recover
    vi.advanceTimersByTime(60_000)
    fire()
    expect(reload).toHaveBeenCalledTimes(2)
  })

  it("does nothing when session storage is unavailable", () => {
    const unavailable = {
      getItem: () => {
        throw new Error("denied")
      },
      setItem: () => {
        throw new Error("denied")
      },
    }
    const { fire, reload } = harness(unavailable)
    expect(fire().defaultPrevented).toBe(false)
    expect(reload).not.toHaveBeenCalled()
  })
})
