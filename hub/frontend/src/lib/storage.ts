// Names and links for storage on other services, e.g., Hugging Face or Box

interface ConnectedStorage {
  kind: string
  bucket: string
}

const STORAGE_SERVICE_NAMES: Record<string, string> = {
  "box-folder": "Box",
  "hf-bucket": "Hugging Face",
}

export const getStorageServiceName = (kind: string): string =>
  STORAGE_SERVICE_NAMES[kind] ?? kind

// For Box, the bucket is the ID of the Calkit folder, which holds every
// project's files
export const getStorageLabel = (r: ConnectedStorage): string =>
  r.kind === "box-folder" ? "Calkit folder" : r.bucket

export const getStorageUrl = (r: ConnectedStorage): string =>
  r.kind === "box-folder"
    ? `https://app.box.com/folder/${r.bucket}`
    : `https://huggingface.co/buckets/${r.bucket}`
