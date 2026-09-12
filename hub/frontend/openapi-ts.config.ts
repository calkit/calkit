import { defineConfig } from "@hey-api/openapi-ts"

export default defineConfig({
  input: "./openapi.json",
  // Write into the existing directory rather than deleting and recreating
  // it: the dev server watches src/client, and a recreated directory is a
  // new inode the watcher never re-attaches to, so nothing it serves
  // updates until the server restarts.
  output: { path: "./src/client", clean: false },
  plugins: [
    {
      name: "@hey-api/client-axios",
      // Throw AxiosError on non-2xx responses (like the legacy client did)
      // instead of returning an error field alongside the response.
      throwOnError: true,
    },
    {
      name: "@hey-api/sdk",
      // Keep class-based exports (UsersService, ProjectsService, etc.)
      operations: {
        strategy: "byTags",
        containerName: "{{name}}Service",
      },
      // Merge path/query/body parameters into a single object per call,
      // matching the legacy calling convention.
      paramsStructure: "flat",
    },
    {
      name: "@hey-api/schemas",
      type: "json",
    },
  ],
})
