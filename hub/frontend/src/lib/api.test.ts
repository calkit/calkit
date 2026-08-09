import type { AxiosResponse } from "axios"
import { describe, expect, it } from "vitest"

import { ProjectsService } from "../client"
import { dataOrNull } from "./api"

const response = (data: unknown) => ({ data }) as AxiosResponse<unknown>

describe("dataOrNull", () => {
  it("restores nulls lost by the generated client and passes data through", async () => {
    // Nullish and coerced-empty bodies become null
    expect(dataOrNull(response(null))).toBeNull()
    expect(dataOrNull(response(undefined))).toBeNull()
    expect(dataOrNull(response({}))).toBeNull()
    // Real bodies pass through untouched, including falsy non-nullish ones
    const showcase = { elements: [] }
    expect(dataOrNull(response(showcase))).toBe(showcase)
    expect(dataOrNull(response([]))).toEqual([])
    expect(dataOrNull(response(0))).toBe(0)
    expect(dataOrNull(response(""))).toBe("")
    // End to end: an endpoint with a nullable response model (e.g. a project
    // with no showcase) returns a null JSON body, which the generated
    // client's `data ?? {}` fallback coerces to a truthy empty object.
    // dataOrNull must restore the null so truthiness guards keep working.
    const nullBodyAxios = async (config: unknown) => ({
      config,
      data: null,
      headers: {},
      status: 200,
      statusText: "OK",
    })
    const call = () =>
      ProjectsService.getProjectShowcase(
        { owner_name: "someone", project_name: "no-showcase" },
        { axios: nullBodyAxios as any },
      )
    await expect(call().then((resp) => resp.data)).resolves.toEqual({})
    await expect(call().then(dataOrNull)).resolves.toBeNull()
  })
})
