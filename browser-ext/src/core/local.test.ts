import { beforeEach, describe, expect, test, vi } from "vitest";

type Listener<T> = (arg: T) => void;

/** A host that answers what it's sent, as the test says. */
class FakePort {
  sent: Record<string, unknown>[] = [];
  disconnected = false;
  private onMessageListeners: Listener<unknown>[] = [];
  private onDisconnectListeners: Listener<void>[] = [];
  onMessage = {
    addListener: (l: Listener<unknown>) => this.onMessageListeners.push(l),
  };
  onDisconnect = {
    addListener: (l: Listener<void>) => this.onDisconnectListeners.push(l),
  };
  postMessage(msg: Record<string, unknown>): void {
    this.sent.push(msg);
  }
  disconnect(): void {
    this.disconnected = true;
  }
  reply(msg: unknown): void {
    this.onMessageListeners.forEach((l) => l(msg));
  }
  close(error?: string): void {
    lastError = error ? { message: error } : undefined;
    this.onDisconnectListeners.forEach((l) => l());
    lastError = undefined;
  }
}

let permitted = true;
let lastError: { message: string } | undefined;
let ports: FakePort[] = [];

function stubChrome(): void {
  vi.stubGlobal("chrome", {
    permissions: { contains: async () => permitted },
    runtime: {
      connectNative: (name: string) => {
        expect(name).toBe("io.calkit.native");
        const port = new FakePort();
        ports.push(port);
        return port;
      },
      get lastError() {
        return lastError;
      },
    },
  });
}

/** Let the promise chain reach postMessage. */
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

describe("askLocal", () => {
  beforeEach(() => {
    permitted = true;
    ports = [];
    vi.resetModules();
    stubChrome();
  });

  test("matches replies to requests, over one connection", async () => {
    const { askLocal } = await import("./local");
    const first = askLocal<{ paths: string[] }>({
      type: "projects.find",
      project: "me/a",
    });
    const second = askLocal({ type: "ping" });
    await settle();
    expect(ports).toHaveLength(1);
    const [port] = ports;
    expect(port.sent.map((m) => m.type)).toEqual(["projects.find", "ping"]);
    // Answered out of order, and one with an error
    port.reply({ id: port.sent[1].id, ok: false, error: "Nope" });
    port.reply({ id: port.sent[0].id, ok: true, result: { paths: ["/a"] } });
    await expect(first).resolves.toEqual({ paths: ["/a"] });
    await expect(second).rejects.toThrow("Nope");
  });

  test("says what to do when the host can't be started", async () => {
    const { askLocal } = await import("./local");
    const asked = askLocal({ type: "ping" });
    await settle();
    ports[0].close("Specified native messaging host not found.");
    await expect(asked).rejects.toThrow("calkit browser-link install");
    // The next request starts it again
    const again = askLocal({ type: "ping" });
    await settle();
    expect(ports).toHaveLength(2);
    ports[1].reply({ id: ports[1].sent[0].id, ok: true, result: {} });
    await expect(again).resolves.toEqual({});
  });

  test("needs the permission first", async () => {
    permitted = false;
    const { askLocal, getLocalStatus } = await import("./local");
    await expect(askLocal({ type: "ping" })).rejects.toThrow("options");
    expect(await getLocalStatus()).toEqual({ permitted: false });
    expect(ports).toHaveLength(0);
  });

  test("reports whether Calkit answers", async () => {
    const { getLocalStatus } = await import("./local");
    const status = getLocalStatus();
    await settle();
    ports[0].reply({
      id: ports[0].sent[0].id,
      ok: true,
      result: { version: "1.2.3", editor: "vscode", editor_installed: false },
    });
    expect(await status).toEqual({
      permitted: true,
      version: "1.2.3",
      editor: "vscode",
      editorInstalled: false,
    });
    const failed = getLocalStatus();
    await settle();
    ports[0].close("Native host has exited.");
    expect(await failed).toEqual({
      permitted: true,
      error: "Calkit on this computer stopped unexpectedly",
    });
    // Granted after the background started, which Chrome doesn't give the
    // API to until the extension reloads
    vi.stubGlobal("chrome", {
      permissions: { contains: async () => true },
      runtime: {},
    });
    expect(await getLocalStatus()).toEqual({
      permitted: true,
      needsReload: true,
    });
  });
});

test("getEditorLabel", async () => {
  const { getEditorLabel } = await import("./local");
  expect(getEditorLabel("vscode")).toBe("VS Code");
  expect(getEditorLabel("cursor --new-window")).toBe("Cursor");
  expect(getEditorLabel("positron")).toBe("Positron");
  expect(getEditorLabel("emacs")).toBe("your editor");
  expect(getEditorLabel(undefined)).toBe("your editor");
});
