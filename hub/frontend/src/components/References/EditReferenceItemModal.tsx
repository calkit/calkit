import {
  Button,
  FormControl,
  FormLabel,
  Input,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalOverlay,
  Select,
  SimpleGrid,
} from "@chakra-ui/react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useEffect, useMemo, useState } from "react"

import type { AxiosError } from "axios"
import { ProjectsService, type ReferenceEntry } from "../../client"
import useCustomToast from "../../hooks/useCustomToast"
import { cleanLatex } from "../../lib/bibtex"
import { handleError } from "../../lib/errors"

interface EditReferenceItemModalProps {
  isOpen: boolean
  onClose: () => void
  ownerName: string
  projectName: string
  bibPath: string
  // Omit to add a new item; provide to edit an existing one.
  entry?: ReferenceEntry
}

const TYPES = [
  "article",
  "book",
  "inproceedings",
  "incollection",
  "inbook",
  "phdthesis",
  "mastersthesis",
  "techreport",
  "unpublished",
  "misc",
]
// Fields shown for every entry type.
const COMMON_FIELDS = ["title", "author", "year", "doi", "url"]
// Extra BibTeX fields per entry type, so the form matches the item (like
// Zotero) instead of a fixed set. Any other field already on the entry is still
// shown so it can be edited, and unshown fields are left untouched by the
// backend.
const TYPE_FIELDS: Record<string, string[]> = {
  article: ["journal", "volume", "number", "pages", "month"],
  book: [
    "editor",
    "publisher",
    "volume",
    "series",
    "edition",
    "address",
    "isbn",
  ],
  inbook: ["chapter", "pages", "publisher", "editor", "series", "address"],
  incollection: [
    "booktitle",
    "publisher",
    "editor",
    "pages",
    "chapter",
    "address",
  ],
  inproceedings: [
    "booktitle",
    "editor",
    "pages",
    "organization",
    "publisher",
    "address",
  ],
  phdthesis: ["school", "address", "month"],
  mastersthesis: ["school", "address", "month"],
  techreport: ["institution", "number", "address", "month"],
  unpublished: ["note", "month"],
  misc: ["howpublished", "note", "month"],
}

const EditReferenceItemModal = ({
  isOpen,
  onClose,
  ownerName,
  projectName,
  bibPath,
  entry,
}: EditReferenceItemModalProps) => {
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const isEdit = Boolean(entry)
  const [type, setType] = useState("article")
  const [key, setKey] = useState("")
  const [fields, setFields] = useState<Record<string, string>>({})

  useEffect(() => {
    if (!isOpen) return
    setType(entry?.type ?? "article")
    setKey(entry?.key ?? "")
    // Load every field on the entry, so existing fields outside the type's
    // standard set are still editable rather than hidden. Show cleaned text
    // (no LaTeX braces/macros), like the reference table and Zotero do.
    const initial: Record<string, string> = {}
    for (const [name, value] of Object.entries(entry?.attrs ?? {})) {
      if (value != null) initial[name] = cleanLatex(String(value))
    }
    setFields(initial)
  }, [isOpen, entry])
  // The fields to show: the type's standard set plus any other field already on
  // the entry.
  const shownFields = useMemo(() => {
    const standard = [...COMMON_FIELDS, ...(TYPE_FIELDS[type] ?? [])]
    const seen = new Set(standard)
    const extras = Object.keys(fields).filter((name) => !seen.has(name))
    return [...standard, ...extras]
  }, [type, fields])
  // Whether the form differs from the entry being edited, so an unchanged edit
  // (which would be a no-op) can't be submitted. A new item is always "dirty".
  const initialFieldValue = (name: string) => {
    const v = entry?.attrs?.[name]
    return v != null ? cleanLatex(String(v)) : ""
  }
  // A BibTeX entry with no fields doesn't survive being read back, so a new
  // item needs at least one, which in practice is the title.
  const hasField = Object.values(fields).some((v) => (v ?? "").trim())
  const canSubmit = Boolean(key.trim()) && (isEdit || hasField)
  const isDirty =
    !isEdit ||
    type !== (entry?.type ?? "article") ||
    key.trim() !== (entry?.key ?? "") ||
    shownFields.some(
      (name) => (fields[name] ?? "").trim() !== initialFieldValue(name).trim(),
    )

  const mutation = useMutation({
    mutationFn: () => {
      // On edit, send only the fields that actually changed, so untouched
      // fields keep their stored (possibly LaTeX) form instead of being
      // rewritten as cleaned text.
      const changed: Record<string, string> = {}
      if (isEdit) {
        for (const name of shownFields) {
          const value = (fields[name] ?? "").trim()
          if (value !== initialFieldValue(name).trim()) changed[name] = value
        }
      } else {
        for (const [name, value] of Object.entries(fields)) {
          if (value.trim()) changed[name] = value.trim()
        }
      }
      const body = { path: bibPath, type, key: key.trim(), fields: changed }
      return isEdit
        ? ProjectsService.putProjectReferenceItem({
            owner_name: ownerName,
            project_name: projectName,
            bib_key: entry!.key,
            referenceItemPut: body,
          }).then((response) => response.data)
        : ProjectsService.postProjectReferenceItem({
            owner_name: ownerName,
            project_name: projectName,
            referenceItemPost: body,
          }).then((response) => response.data)
    },
    onSuccess: () => {
      showToast(
        "Success!",
        isEdit ? "Reference updated." : "Reference added.",
        "success",
      )
      queryClient.invalidateQueries({
        queryKey: ["projects", ownerName, projectName, "references"],
      })
      onClose()
    },
    onError: (err: AxiosError) => handleError(err, showToast),
  })

  return (
    <Modal isOpen={isOpen} onClose={onClose} size="xl" isCentered>
      <ModalOverlay />
      <ModalContent
        as="form"
        autoComplete="off"
        onSubmit={(e) => {
          e.preventDefault()
          if (canSubmit && isDirty) mutation.mutate()
        }}
        onKeyDown={(e) => {
          if (
            (e.metaKey || e.ctrlKey) &&
            e.key === "Enter" &&
            canSubmit &&
            isDirty
          ) {
            e.preventDefault()
            mutation.mutate()
          }
        }}
      >
        <ModalHeader>{isEdit ? "Edit reference" : "Add reference"}</ModalHeader>
        <ModalCloseButton />
        <ModalBody pb={6}>
          <SimpleGrid columns={2} spacing={3}>
            <FormControl>
              <FormLabel>Type</FormLabel>
              <Select value={type} onChange={(e) => setType(e.target.value)}>
                {TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </Select>
            </FormControl>
            <FormControl isRequired>
              <FormLabel>Citation key</FormLabel>
              <Input
                value={key}
                onChange={(e) => setKey(e.target.value)}
                placeholder="e.g. smith2020"
                autoComplete="off"
                data-form-type="other"
                data-lpignore="true"
              />
            </FormControl>
            {shownFields.map((name) => (
              <FormControl key={name}>
                <FormLabel textTransform="capitalize">{name}</FormLabel>
                <Input
                  value={fields[name] ?? ""}
                  onChange={(e) =>
                    setFields((f) => ({ ...f, [name]: e.target.value }))
                  }
                  autoComplete="off"
                  data-form-type="other"
                  data-lpignore="true"
                />
              </FormControl>
            ))}
          </SimpleGrid>
        </ModalBody>
        <ModalFooter gap={3}>
          <Button
            variant="primary"
            type="submit"
            isDisabled={!canSubmit || !isDirty}
            isLoading={mutation.isPending}
          >
            {isEdit ? "Save" : "Add"}
          </Button>
          <Button type="button" onClick={onClose}>
            Cancel
          </Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  )
}

export default EditReferenceItemModal
