import { URLExt } from "@jupyterlab/coreutils";

import { ServerConnection } from "@jupyterlab/services";

/**
 * Call the server extension
 *
 * @param endPoint API REST end point for the extension
 * @param init Initial values for the request
 * @returns The response body interpreted as JSON
 */
export async function requestAPI<T>(
  endPoint = "",
  init: RequestInit = {},
): Promise<T> {
  // Make request to Jupyter API
  const settings = ServerConnection.makeSettings();
  const requestUrl = URLExt.join(
    settings.baseUrl,
    "calkit", // our server extension's API namespace
    endPoint,
  );

  let response: Response;
  try {
    response = await ServerConnection.makeRequest(requestUrl, init, settings);
  } catch (error) {
    throw new ServerConnection.NetworkError(error as any);
  }

  let data: any = await response.text();

  if (data.length > 0) {
    try {
      data = JSON.parse(data);
    } catch (error) {
      console.log("Not a JSON response body.", response);
      console.log("Requested URL:", requestUrl);
      console.log("Response text:", data.substring(0, 500));
    }
  }

  if (!response.ok) {
    // Extract error message from various possible formats
    let errorMessage: string;
    if (typeof data === "string") {
      errorMessage = data;
    } else if (data && typeof data === "object") {
      // Try common error message fields
      errorMessage =
        data.message || data.error || data.reason || JSON.stringify(data);
    } else {
      errorMessage = "An error occurred";
    }
    throw new ServerConnection.ResponseError(response, errorMessage);
  }

  return data;
}
