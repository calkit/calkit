import { useCallback, useEffect, useMemo, useRef, useState } from "react"

import { MachineConnection, type SessionInfo } from "./connection"

// A page's connections to machines through the relay, one each, open
// while they're online and closed when the page goes, and the sessions on
// each. refetchOnline updates the list of online ones, which is called more
// often while a connection is lost, so it's back soon after its machine is.
export default function useMachineConnections(
  online: string[],
  refetchOnline?: () => void,
) {
  const connections = useRef(new Map<string, MachineConnection>())
  const [, setVersion] = useState(0)
  const rerender = useCallback(() => setVersion((v) => v + 1), [])
  // Listed over the relay, so undefined until a machine answers
  const [sessions, setSessions] = useState<Record<string, SessionInfo[]>>({})
  // Stable while the set of machines is, however the list was built
  const onlineKey = [...new Set(online)].sort().join(",")
  const onlineMachines = useMemo(
    () => (onlineKey ? onlineKey.split(",") : []),
    [onlineKey],
  )
  // Any machine's, which only connects while it's online
  const getConnection = useCallback(
    (machineId: string) => {
      let conn = connections.current.get(machineId)
      if (!conn) {
        conn = new MachineConnection(machineId)
        conn.statusListeners.add(rerender)
        connections.current.set(machineId, conn)
        if (onlineMachines.includes(machineId)) conn.open()
      }
      return conn
    },
    [rerender, onlineMachines],
  )
  useEffect(() => {
    for (const machineId of onlineMachines) getConnection(machineId).open()
    // Gone offline, so asking for relay tokens would only be refused
    for (const [machineId, conn] of connections.current) {
      if (!onlineMachines.includes(machineId)) conn.close()
    }
  }, [onlineMachines, getConnection])
  useEffect(() => {
    const conns = connections.current
    return () => {
      for (const conn of conns.values()) conn.close()
      conns.clear()
    }
  }, [])
  const refreshSessions = useCallback(async () => {
    const next: Record<string, SessionInfo[]> = {}
    for (const [machineId, conn] of connections.current) {
      if (!conn.connected) continue
      try {
        next[machineId] = (await conn.request("sessions.list")).sessions
      } catch {
        // Shown as disconnected instead
      }
    }
    setSessions(next)
  }, [])
  useEffect(() => {
    // Sessions are per machine, so refresh when the set of them changes
    if (onlineMachines.length) refreshSessions()
    const interval = window.setInterval(refreshSessions, 5000)
    return () => window.clearInterval(interval)
  }, [refreshSessions, onlineMachines])
  const lost = [...connections.current.values()].some(
    (c) => c.wasConnected && !c.connected,
  )
  const refetchRef = useRef(refetchOnline)
  refetchRef.current = refetchOnline
  useEffect(() => {
    if (!lost) return
    const interval = window.setInterval(() => refetchRef.current?.(), 5000)
    return () => window.clearInterval(interval)
  }, [lost])
  // Why connecting was refused, if the user has to do something about it
  const secondFactorError =
    [...connections.current.values()].find((c) => c.error)?.error ?? null
  const retryRefused = () => {
    for (const conn of connections.current.values()) {
      if (conn.error) conn.retryNow()
    }
  }
  return {
    connections: connections.current,
    getConnection,
    onlineMachines,
    sessions,
    refreshSessions,
    secondFactorError,
    retryRefused,
  }
}
