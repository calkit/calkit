import { defineConfig } from "@hey-api/openapi-ts";

export default defineConfig({
  input: "./openapi.json",
  output: "./src/client",
  plugins: [
    "legacy/axios",
    {
      name: "@hey-api/sdk",
      // Keep class-based exports (UsersService, ProjectsService, etc.)
      asClass: true,
      operationId: true,
      classNameBuilder: "{{name}}Service",
      methodNameBuilder: (operation) => {
        // The plugin augments this object shape at runtime.
        // @ts-expect-error runtime shape from openapi-ts plugin
        let name: string = operation.name;
        // @ts-expect-error runtime shape from openapi-ts plugin
        const service: string = operation.service;

        if (service && name.toLowerCase().startsWith(service.toLowerCase())) {
          name = name.slice(service.length);
        }

        return name.charAt(0).toLowerCase() + name.slice(1);
      },
    },
    {
      name: "@hey-api/schemas",
      type: "json",
    },
  ],
});
