// Runs the simulation in Pyodide, so it uses the visitor's compute rather
// than a server's. The page starts several of these to run in parallel.
import { loadPyodide } from "https://cdn.jsdelivr.net/pyodide/v314.0.7/full/pyodide.mjs";

const ready = (async () => {
  const pyodide = await loadPyodide();
  await pyodide.loadPackage(["numpy", "micropip"]);
  await pyodide.runPythonAsync(
    'import micropip; await micropip.install("simpy==4.1.2")',
  );
  for (const name of ["research_flow.py", "simulator.py"]) {
    const response = await fetch(new URL(name, import.meta.url));
    pyodide.FS.writeFile(`/home/pyodide/${name}`, await response.text());
  }
  pyodide.runPython("import sys; sys.path.insert(0, '/home/pyodide')");
  return pyodide.pyimport("simulator");
})();

onmessage = async ({ data }) => {
  try {
    const simulator = await ready;
    const result = simulator.handle(JSON.stringify(data));
    postMessage({ id: data.id, result: JSON.parse(result) });
  } catch (error) {
    postMessage({ id: data.id, error: String(error) });
  }
};
