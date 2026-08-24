import { defineConfig } from "@hey-api/openapi-ts"

export default defineConfig({
  input: "./openapi.json",
  output: "./src/client",
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
