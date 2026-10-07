// The simulator page: a form for a visitor's workflow, a pool of Pyodide
// workers that simulate it, and charts of what comes back
const POOL_SIZE = Math.max(
  1,
  Math.min(4, (navigator.hardwareConcurrency || 2) - 1),
);
// Runs per message to a worker, small enough to spread a scenario over the
// pool and show progress
const CHUNK = 25;
// Stage fields entered as percentages
const PERCENT = ["agent_work", "hop_error"];
const POLICIES = {
  "stage-gate": "Stage by stage, reviewed in batches",
  lean: "In small steps, reviewed at regular meetings",
};
const REVIEWERS = {
  browser: "The browser, with an AI assistant",
  word: "Word, via the round trip",
};
const SETTINGS = [
  ["n_findings", "Findings in the paper", { min: 1, step: 1 }],
  ["policy", "How you work today", { options: POLICIES }],
  ["agents", "You use AI agents", { checkbox: true }],
  ["pi_hours_per_week", "PI hours per week for your work", {}],
  ["review_interval", "Working days between PI meetings, in small steps", {}],
  ["prep_fixed", "Days to prepare for a PI review", {}],
  ["prep_item", "Days more per finding reviewed", {}],
  ["review_days", "Working days per round of peer review", {}],
  ["pi_reviews_in", "With Calkit, your PI reviews in", { options: REVIEWERS }],
  ["reps", "Runs per scenario", { min: 20, max: 2000, step: 1 }],
];

class Pool {
  constructor(size, onError) {
    this.idle = [];
    this.queue = [];
    this.pending = new Map();
    this.nextId = 0;
    for (let i = 0; i < size; i++) {
      const worker = new Worker(new URL("worker.js", import.meta.url), {
        type: "module",
      });
      worker.onmessage = ({ data }) => {
        const { resolve, reject } = this.pending.get(data.id);
        this.pending.delete(data.id);
        this.idle.push(worker);
        this.drain();
        if (data.error) reject(new Error(data.error));
        else resolve(data.result);
      };
      worker.onerror = (event) => onError(event.message || "worker failed");
      this.idle.push(worker);
    }
  }

  call(call, ...args) {
    return new Promise((resolve, reject) => {
      this.queue.push({ call, args, resolve, reject });
      this.drain();
    });
  }

  drain() {
    while (this.idle.length && this.queue.length) {
      const worker = this.idle.shift();
      const { call, args, resolve, reject } = this.queue.shift();
      const id = this.nextId++;
      this.pending.set(id, { resolve, reject });
      worker.postMessage({ id, call, args });
    }
  }
}

const root = document.getElementById("simulator");
const capitalize = (s) => s[0].toUpperCase() + s.slice(1);
const days = (d) => `${Math.round(d).toLocaleString()}`;
const months = (d) => (d / 21).toFixed(1);
const escape = (s) =>
  String(s).replace(
    /[&<>"]/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c],
  );
let state;

function showError(message) {
  root.querySelector(
    ".sim-status",
  ).textContent = `Something went wrong: ${message}`;
}

function field(key, label, opts) {
  const value = state[key];
  const input = opts.checkbox
    ? `<input type="checkbox" data-key="${key}" ${value ? "checked" : ""}>`
    : opts.options
    ? `<select data-key="${key}">${Object.entries(opts.options)
        .map(
          ([v, text]) =>
            `<option value="${v}"${
              v === value ? " selected" : ""
            }>${text}</option>`,
        )
        .join("")}</select>`
    : `<input type="number" data-key="${key}" value="${value}"
        min="${opts.min ?? 0}" step="${opts.step ?? "any"}"
        ${opts.max ? `max="${opts.max}"` : ""}>`;
  return `<label class="sim-field"><span>${label}</span>${input}</label>`;
}

function stageRows() {
  const last = state.stages.length - 1;
  return state.stages
    .map(
      (s, i) => `<tr>
        <td><input type="text" data-stage="${i}" data-field="name"
          autocomplete="off" data-form-type="other" data-lpignore="true"
          data-1p-ignore
          value="${escape(s.name)}" aria-label="Stage name"></td>
        <td><input type="number" data-stage="${i}" data-field="work"
          value="${s.work}" min="0.1" step="any"
          aria-label="Days of work per finding"></td>
        <td><input type="number" data-stage="${i}" data-field="agent_work"
          value="${+(s.agent_work * 100).toFixed(2)}" min="1" step="any"
          aria-label="Percent of that time it takes with AI agents"></td>
        <td>${
          i < last
            ? `<input type="checkbox" data-stage="${i}" data-field="hop"
                ${s.hop ? "checked" : ""}
                aria-label="Moved into the next stage's tools by hand">`
            : ""
        }</td>
        <td>${
          i < last
            ? `<input type="number" data-stage="${i}" data-field="hop_hours"
                value="${s.hop_hours}" min="0" step="any"
                ${s.hop ? "" : "disabled"} aria-label="Hours per move">`
            : ""
        }</td>
        <td>${
          i < last
            ? `<input type="number" data-stage="${i}" data-field="hop_error"
                value="${+(s.hop_error * 100).toFixed(2)}" min="0" max="100"
                step="any" ${s.hop ? "" : "disabled"}
                aria-label="Percent of moves that get something wrong">`
            : ""
        }</td>
        <td><button type="button" class="sim-remove" data-remove="${i}"
          ${state.stages.length <= 3 ? "disabled" : ""}
          aria-label="Remove stage">✕</button></td>
      </tr>`,
    )
    .join("");
}

function renderForm() {
  root.innerHTML = `
    <form class="sim-form" autocomplete="off" data-form-type="other">
      <h2>Your workflow</h2>
      <div class="sim-table-wrap"><table class="sim-stages">
        <thead><tr>
          <th>Stage</th><th>Days of work per finding</th>
          <th>Time it takes with AI agents (%)</th>
          <th>Moved to the next stage's tools by hand</th>
          <th>Hours per move</th>
          <th>Moves that get something wrong (%)</th><th></th>
        </tr></thead>
        <tbody>${stageRows()}</tbody>
      </table></div>
      <button type="button" class="md-button sim-add">Add a stage</button>
      <div class="sim-settings">${SETTINGS.map(([k, label, opts]) =>
        field(k, label, opts),
      ).join("")}</div>
      <button type="submit" class="md-button md-button--primary sim-run">
        Simulate</button>
      <span class="sim-status"></span>
      <progress class="sim-progress" max="1" value="0" hidden></progress>
    </form>
    <div class="sim-results"></div>
    <div class="sim-tip" role="tooltip" hidden></div>`;
  const form = root.querySelector("form");
  form.addEventListener("input", (event) => {
    const t = event.target;
    if (t.dataset.key) {
      state[t.dataset.key] =
        t.type === "checkbox"
          ? t.checked
          : t.tagName === "SELECT"
          ? t.value
          : +t.value;
    } else if (t.dataset.stage) {
      const stage = state.stages[+t.dataset.stage];
      const f = t.dataset.field;
      stage[f] =
        t.type === "checkbox" ? t.checked : f === "name" ? t.value : +t.value;
      if (PERCENT.includes(f)) stage[f] /= 100;
      if (f === "hop") {
        for (const g of ["hop_hours", "hop_error"]) {
          form.querySelector(
            `[data-stage="${t.dataset.stage}"][data-field="${g}"]`,
          ).disabled = !t.checked;
        }
      }
    }
  });
  form.addEventListener("click", (event) => {
    const remove = event.target.closest("[data-remove]");
    if (event.target.closest(".sim-add")) {
      state.stages.push({
        ...state.new_stage,
        name: `stage ${state.stages.length + 1}`,
      });
    } else if (remove) {
      state.stages.splice(+remove.dataset.remove, 1);
    } else {
      return;
    }
    form.querySelector("tbody").innerHTML = stageRows();
  });
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (form.reportValidity()) simulate();
  });
}

function extent(rows) {
  // From zero to the furthest bar or interval, which charts compared with
  // each other share
  const lo = Math.min(0, ...rows.map((r) => r.low ?? r.value));
  const hi = Math.max(...rows.map((r) => r.high ?? r.value), 1e-9);
  return [lo, hi];
}

function bars(rows, [lo, hi] = extent(rows)) {
  // Horizontal bars from zero, with a whisker for each interval
  const x = (v) => ((v - lo) / (hi - lo)) * 100;
  return `<div class="sim-bars">${rows
    .map((r) => {
      const left = Math.min(x(0), x(r.value));
      const width = Math.abs(x(r.value) - x(0));
      const whisker =
        r.low !== undefined
          ? `<span class="sim-whisker" style="left:${x(r.low)}%;
            width:${x(r.high) - x(r.low)}%"></span>`
          : "";
      return `<div class="sim-bar-row" data-tip="${escape(r.tip)}">
        <span class="sim-bar-label">${escape(r.label)}</span>
        <span class="sim-bar-plot">
          <span class="sim-zero" style="left:${x(0)}%"></span>
          <span class="sim-bar${r.value < 0 ? " sim-bar--negative" : ""}"
            style="left:${left}%;width:${width}%"></span>${whisker}
        </span>
        <span class="sim-bar-value">${days(r.value)}</span>
      </div>`;
    })
    .join("")}</div>`;
}

function renderReport(report) {
  const { today, first, later } = report;
  const tile = (label, value, note) => `<div class="sim-tile">
      <span class="sim-tile-label">${label}</span>
      <span class="sim-tile-value">${days(value)}</span>
      <span class="sim-tile-note">${note}</span></div>`;
  const saving = (c, label = c.name) => ({
    label,
    value: c.saved,
    low: c.low,
    high: c.high,
    tip:
      `${days(c.saved)} working days saved per paper ` +
      `(95% interval ${days(c.low)} to ${days(c.high)}): ` +
      `${days(c.days)} to a published paper instead of ${days(today.days)}`,
  });
  const parts = report.parts.map((c) => saving(c));
  const without = [
    report.small_steps &&
      saving(report.small_steps, "Working in small steps, with today's tools"),
    report.agents && saving(report.agents),
  ].filter(Boolean);
  // One scale for both, so Calkit's parts compare with what's possible
  // without it
  const scale = extent([...parts, ...without]);
  const breakdown = Object.entries(today.breakdown).map(([k, v]) => ({
    label: capitalize(k),
    value: v,
    tip: `${days(v)} working days, ${Math.round((v / today.days) * 100)}%`,
  }));
  const unfinished = today.unfinished + first.unfinished + later.unfinished;
  const agents = report.uses_agents ? ", with AI agents" : "";
  root.querySelector(".sim-results").innerHTML = `
    <h2>Working days to a published paper</h2>
    <div class="sim-tiles">
      ${tile(
        `Today${agents}`,
        today.days,
        `${months(today.days)} months; 80% of runs
        ${days(today.p10)}–${days(today.p90)}`,
      )}
      ${tile(
        `With Calkit${agents}, first paper`,
        first.days,
        `${first.ratio.toFixed(2)}× as fast, including
        ${days(first.learning_days)} days learning Calkit`,
      )}
      ${tile(
        `With Calkit${agents}, later papers`,
        later.days,
        `${later.ratio.toFixed(2)}× as fast`,
      )}
    </div>
    ${
      unfinished
        ? `<p class="sim-warning">${unfinished} runs hadn't published
          after 5,000 working days and were cut off there.</p>`
        : ""
    }
    <h2>What each part of Calkit saves</h2>
    <p class="sim-caption">Working days saved per paper by each part of
      Calkit added to how you work today on its own, with 95% intervals,
      from ${report.reps} runs each.</p>
    ${bars(parts, scale)}
    <h2>Without Calkit</h2>
    <p class="sim-caption">Working days saved per paper by each change on
      its own, on the same scale.</p>
    ${
      without.length
        ? bars(without, scale)
        : `<p class="sim-caption">You already work in small steps and use
            AI agents.</p>`
    }
    <h2>Where today's time goes</h2>
    <p class="sim-caption">Working days per paper.</p>
    ${bars(breakdown)}`;
}

async function simulate() {
  const button = root.querySelector(".sim-run");
  const status = root.querySelector(".sim-status");
  const progress = root.querySelector(".sim-progress");
  const inputs = structuredClone(state);
  button.disabled = true;
  try {
    const names = await pool.call("plan", inputs);
    const runs = Object.fromEntries(
      names.map((n) => [n, new Array(inputs.reps)]),
    );
    const total = names.length * inputs.reps;
    let done = 0;
    progress.hidden = false;
    progress.value = 0;
    status.textContent = `Running ${names.length} scenarios`;
    const started = performance.now();
    const jobs = [];
    for (const name of names) {
      for (let start = 0; start < inputs.reps; start += CHUNK) {
        const stop = Math.min(start + CHUNK, inputs.reps);
        jobs.push(
          pool.call("run", inputs, name, start, stop).then((out) => {
            // Chunks land out of order, so each goes in by seed
            runs[name].splice(start, out.length, ...out);
            done += out.length;
            progress.value = done / total;
          }),
        );
      }
    }
    await Promise.all(jobs);
    renderReport(await pool.call("report", inputs, runs));
    const seconds = ((performance.now() - started) / 1000).toFixed(1);
    status.textContent = `Ran ${total.toLocaleString()} simulations in
      ${seconds} s on ${POOL_SIZE} workers`;
  } catch (error) {
    showError(error.message);
  } finally {
    button.disabled = false;
    progress.hidden = true;
  }
}

function followTips() {
  const tip = root.querySelector(".sim-tip");
  root.addEventListener("pointermove", (event) => {
    const row = event.target.closest("[data-tip]");
    if (!row) {
      tip.hidden = true;
      return;
    }
    tip.textContent = row.dataset.tip;
    tip.hidden = false;
    const x = Math.min(event.clientX + 12, window.innerWidth - 300);
    tip.style.left = `${Math.max(8, x)}px`;
    tip.style.top = `${event.clientY + 16}px`;
  });
  root.addEventListener("pointerleave", () => (tip.hidden = true));
}

root.innerHTML = `<p class="sim-status">Loading Python in your browser…</p>`;
const pool = new Pool(POOL_SIZE, showError);
pool
  .call("defaults")
  .then((defaults) => {
    state = defaults;
    renderForm();
    followTips();
  })
  .catch((error) => showError(error.message));
