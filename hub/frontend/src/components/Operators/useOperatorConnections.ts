import { useCallback, useEffect, useMemo, useRef, useState } from "react"

import { OperatorConnection, type SessionInfo } from "./connection"

// A page's connections to Operators through the relay, one each, opened
// for the online ones and closed when the page goes, and the sessions on
// each
export default function useOperatorConnections(online: string[]) {
  const connections = useRef(new Map<string, OperatorConnection>())
  const [, setVersion] = useState(0)
  const rerender = useCallback(() => setVersion((v) => v + 1), [])
  // Listed over the relay, so undefined until an Operator answers
  const [sessions, setSessions] = useState<Record<string, SessionInfo[]>>({})
  const getConnection = useCallback(
    (operatorId: string) => {
      let conn = connections.current.get(operatorId)
      if (!conn) {
        conn = new OperatorConnection(operatorId)
        conn.statusListeners.add(rerender)
        connections.current.set(operatorId, conn)
      }
      return conn
    },
    [rerender],
  )
  // Stable while the set of Operators is, however the list was built
  const onlineKey = [...new Set(online)].sort().join(",")
  const onlineOperators = useMemo(
    () => (onlineKey ? onlineKey.split(",") : []),
    [onlineKey],
  )
  useEffect(() => {
    for (const operatorId of onlineOperators) getConnection(operatorId)
  }, [onlineOperators, getConnection])
  useEffect(() => {
    const conns = connections.current
    return () => {
      for (const conn of conns.values()) conn.close()
      conns.clear()
    }
  }, [])
  const refreshSessions = useCallback(async () => {
    const next: Record<string, SessionInfo[]> = {}
    for (const [operatorId, conn] of connections.current) {
      if (!conn.connected) continue
      try {
        next[operatorId] = (await conn.request("sessions.list")).sessions
      } catch {
        // Shown as disconnected instead
      }
    }
    setSessions(next)
  }, [])
  useEffect(() => {
    // Sessions are per Operator, so refresh when the set of them changes
    if (onlineOperators.length) refreshSessions()
    const interval = window.setInterval(refreshSessions, 5000)
    return () => window.clearInterval(interval)
  }, [refreshSessions, onlineOperators])
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
    onlineOperators,
    sessions,
    refreshSessions,
    secondFactorError,
    retryRefused,
  }
}
