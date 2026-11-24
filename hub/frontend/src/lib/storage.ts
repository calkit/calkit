// Names and links for storage on other services, e.g., Hugging Face or Box

interface ConnectedStorage {
  kind: string
  bucket: string
}

export const getStorageServiceName = (kind: string): string =>
  kind === "box-folder" ? "Box" : "Hugging Face"

// For Box, the bucket is the ID of the Calkit folder, which holds every
// project's files
export const getStorageLabel = (r: ConnectedStorage): string =>
  r.kind === "box-folder" ? "Calkit folder" : r.bucket

export const getStorageUrl = (r: ConnectedStorage): string =>
  r.kind === "box-folder"
    ? `https://app.box.com/folder/${r.bucket}`
    : `https://huggingface.co/buckets/${r.bucket}`
