import {
  Badge,
  Box,
  Code,
  Flex,
  IconButton,
  useColorModeValue,
} from "@chakra-ui/react"
import { FitAddon } from "@xterm/addon-fit"
import { Terminal } from "@xterm/xterm"
import "@xterm/xterm/css/xterm.css"
import { useEffect, useRef, useState } from "react"
import { FiMinus, FiX } from "react-icons/fi"

import Tooltip from "../Common/Tooltip"
import type { MachineConnection, Pane } from "./connection"

// The relay drops a message over 256 KiB, so a long paste goes in pieces
// that fit even with every character escaped as JSON twice
const MAX_INPUT_CHARS = 32 * 1024

export default function TerminalPane({
  conn,
  pane,
  label,
  connected,
  onClose,
  onDetach,
  height = "352px",
}: {
  conn: MachineConnection
  pane: Pane
  label: string
  connected: boolean
  onClose: () => void
  onDetach: () => void
  height?: string
}) {
  const ref = useRef<HTMLDivElement>(null)
  const termRef = useRef<Terminal | null>(null)
  const fitRef = useRef<FitAddon | null>(null)
  const [exited, setExited] = useState<number | null | undefined>(undefined)
  const headerBg = useColorModeValue("gray.100", "gray.700")
  // The terminal lives as long as the pane
  useEffect(() => {
    const term = new Terminal({
      cursorBlink: true,
      fontSize: 13,
      fontFamily: "Menlo, Monaco, 'Courier New', monospace",
      scrollback: 5000,
    })
    const fit = new FitAddon()
    term.loadAddon(fit)
    term.open(ref.current!)
    fit.fit()
    termRef.current = term
    fitRef.current = fit
    // Replayed chunks still being written, during which the terminal's
    // replies to queries in them, e.g., a cursor position report, are
    // dropped: they were answered when first asked, and would now reach the
    // shell as text
    let replaying = 0
    const input = term.onData((data) => {
      if (replaying) return
      for (let start = 0; start < data.length; ) {
        let end = Math.min(start + MAX_INPUT_CHARS, data.length)
        // Not between the two halves of a character outside the BMP
        if (end < data.length && /[\uD800-\uDBFF]/.test(data[end - 1])) end--
        conn.send({
          type: "sessions.input",
          session: pane.session,
          data: data.slice(start, end),
        })
        start = end
      }
    })
    const resize = term.onResize(({ cols, rows }) =>
      conn.send({ type: "sessions.resize", session: pane.session, cols, rows }),
    )
    const unsubscribe = conn.onSession(pane.session, (msg) => {
      if (msg.type === "sessions.output") {
        // Replays start by clearing the screen they redraw. It's written as
        // a reset sequence rather than calling reset(), which would take
        // effect before earlier writes that are still queued
        const data = msg.reset ? `\x1bc${msg.data}` : msg.data
        if (msg.replay) {
          replaying++
          term.write(data, () => replaying--)
        } else {
          term.write(data)
        }
      }
      if (msg.type === "sessions.exit") setExited(msg.code)
    })
    const observer = new ResizeObserver(() => fit.fit())
    observer.observe(ref.current!)
    return () => {
      observer.disconnect()
      unsubscribe()
      input.dispose()
      resize.dispose()
      term.dispose()
    }
  }, [conn, pane.session])
  // Attach whenever the connection is (re)established; the link replays
  // recent output onto a cleared screen
  useEffect(() => {
    const term = termRef.current
    if (!connected || !term) return
    conn
      .request("sessions.attach", {
        session: pane.session,
        cols: term.cols,
        rows: term.rows,
      })
      .catch((e) => term.write(`\r\n[${e.message}]\r\n`))
  }, [conn, connected, pane.session])
  return (
    <Box borderWidth={1} borderRadius="md" overflow="hidden" mb={3}>
      <Flex bg={headerBg} px={2} py={1} align="center" gap={2}>
        <Code fontSize="xs">{label}</Code>
        {!connected && <Badge colorScheme="orange">Reconnecting</Badge>}
        {exited !== undefined && (
          <Badge colorScheme="gray">Exited ({exited ?? "?"})</Badge>
        )}
        <Box flex={1} />
        <Tooltip label="Hide (stays running)">
          <IconButton
            aria-label="Hide session"
            icon={<FiMinus />}
            size="xs"
            variant="ghost"
            onClick={onDetach}
          />
        </Tooltip>
        <Tooltip label="End session">
          <IconButton
            aria-label="End session"
            icon={<FiX />}
            size="xs"
            variant="ghost"
            onClick={onClose}
          />
        </Tooltip>
      </Flex>
      {/* The padding is on a wrapper, since the fit addon sizes the
          terminal to its element's full height, padding included, which
          would cut off the last row */}
      <Box bg="black" p={1}>
        <Box ref={ref} h={height} />
      </Box>
    </Box>
  )
}
