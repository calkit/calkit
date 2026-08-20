import {
  Box,
  Input,
  List,
  ListItem,
  Spinner,
  Text,
  useColorModeValue,
} from "@chakra-ui/react"
import { useState } from "react"

import { fuzzyFilter } from "../../lib/fuzzy"

export interface SelectOption {
  value: string
  /** Shown next to the value, e.g. "private" or a file size. */
  hint?: string
}

interface FilterableSelectProps {
  options: SelectOption[]
  onSelect: (value: string) => void
  /** Current value, when the caller wants to control the input. */
  value?: string
  onChange?: (value: string) => void
  placeholder?: string
  isLoading?: boolean
  id?: string
  /** Shown in place of the list when nothing matches what was typed. */
  emptyMessage?: string
}

/**
 * A text input that filters a list as you type.
 *
 * A plain select stops working somewhere past a few dozen options, which
 * is where both of its uses here land: a GitHub account's repos, and every
 * file in a project. Typing is also how someone with the name half in mind
 * finds it, which scrolling isn't.
 *
 * The typed text is the value: a caller can accept something that isn't in
 * the list (a repo the API didn't return, a path that doesn't exist yet)
 * by reading `onChange` rather than only `onSelect`.
 */
const FilterableSelect = ({
  options,
  onSelect,
  value,
  onChange,
  placeholder,
  isLoading,
  id,
  emptyMessage,
}: FilterableSelectProps) => {
  const [internal, setInternal] = useState("")
  const query = value ?? internal
  const [open, setOpen] = useState(false)
  const [highlighted, setHighlighted] = useState(0)
  const listBg = useColorModeValue("white", "gray.700")
  const borderColor = useColorModeValue("gray.200", "gray.600")
  const hoverBg = useColorModeValue("gray.100", "gray.600")
  const matches = fuzzyFilter(options, query, (option) => option.value)
  const setQuery = (next: string) => {
    setInternal(next)
    onChange?.(next)
  }
  const choose = (option: SelectOption) => {
    setQuery(option.value)
    setOpen(false)
    onSelect(option.value)
  }
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (!open || !matches.length) return
    if (e.key === "ArrowDown") {
      e.preventDefault()
      setHighlighted((h) => (h + 1) % matches.length)
    } else if (e.key === "ArrowUp") {
      e.preventDefault()
      setHighlighted((h) => (h - 1 + matches.length) % matches.length)
    } else if (e.key === "Enter") {
      // This lives inside a form, so Enter must not submit it while a
      // suggestion is being chosen.
      e.preventDefault()
      choose(matches[Math.min(highlighted, matches.length - 1)])
    } else if (e.key === "Escape") {
      setOpen(false)
    }
  }
  const showEmpty =
    open && !isLoading && !matches.length && Boolean(query) && emptyMessage
  return (
    <Box position="relative">
      <Input
        id={id}
        value={query}
        placeholder={isLoading ? "Loading…" : placeholder}
        autoComplete="off"
        onChange={(e) => {
          setQuery(e.target.value)
          setHighlighted(0)
          setOpen(true)
        }}
        onFocus={() => setOpen(true)}
        // Choosing an option keeps focus in the input (the mousedown handler
        // prevents the default blur), so clicking back into it fires no
        // focus event and the list would stay shut.
        onClick={() => setOpen(true)}
        // Deferred so a click on a suggestion lands before the list closes.
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        onKeyDown={onKeyDown}
      />
      {isLoading ? (
        <Spinner
          size="sm"
          position="absolute"
          right={3}
          top="50%"
          transform="translateY(-50%)"
        />
      ) : null}
      {open && matches.length > 0 ? (
        <List
          position="absolute"
          zIndex={10}
          mt={1}
          width="100%"
          bg={listBg}
          borderWidth={1}
          borderColor={borderColor}
          borderRadius="md"
          boxShadow="md"
          maxH="240px"
          overflowY="auto"
        >
          {matches.map((option, index) => (
            <ListItem
              key={option.value}
              px={3}
              py={2}
              cursor="pointer"
              bg={index === highlighted ? hoverBg : undefined}
              _hover={{ bg: hoverBg }}
              onMouseEnter={() => setHighlighted(index)}
              onMouseDown={(e) => {
                // mousedown, not click: blur would close the list first.
                e.preventDefault()
                choose(option)
              }}
            >
              <Text fontSize="sm" wordBreak="break-all">
                {option.value}
                {option.hint ? (
                  <Text as="span" color="ui.dim" fontSize="xs" ml={2}>
                    {option.hint}
                  </Text>
                ) : null}
              </Text>
            </ListItem>
          ))}
        </List>
      ) : null}
      {showEmpty ? (
        <Text fontSize="xs" color="ui.dim" mt={1}>
          {emptyMessage}
        </Text>
      ) : null}
    </Box>
  )
}

export default FilterableSelect
