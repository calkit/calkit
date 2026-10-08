// The simulator page: a form for a visitor's workflow, a pool of Pyodide
// workers that simulate it, and charts of what comes back
const POOL_SIZE = Math.max(
  1,
  Math.min(4, (navigator.hardwareConcurrency || 2) - 1),
);
const SOURCE = "https://github.com/calkit/calkit";
// Runs per message to a worker, small enough to spread a scenario over the
// pool and show progress
const CHUNK = 25;
// Stage fields entered as percentages
const PERCENT = ["agent_work", "hop_error"];
const POLICIES = {
  "stage-gate":
    "All results through each step before the next, e.g., every " +
    "experiment, then every analysis, with a PI review after each step",
  lean:
    "One result at a time, through to a draft, before starting the next, " +
    "with PI reviews at regular meetings",
};
const REVIEWERS = {
  browser: "The browser",
  word: "Word, via the round trip",
};
const SETTINGS = [
  ["n_findings", "Results worth writing up in the paper", { min: 1, step: 1 }],
  ["policy", "How you work through your results today", { radio: POLICIES }],
  ["agents", "You use AI agents", { checkbox: true }],
  ["pi_hours_per_week", "PI hours per week for your work", {}],
  [
    "review_interval",
    "Working days between PI reviews, one result at a time",
    {},
  ],
  ["prep_fixed", "Days to prepare for a PI review", {}],
  ["prep_item", "Days more per result reviewed", {}],
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

// Material's analytics keeps its gtag to itself, so this pushes to its
// dataLayer the same way, as gtag.js only reads Arguments objects from it
function track() {
  window.dataLayer?.push(arguments);
}

function showError(message) {
  root.querySelector(
    ".sim-status",
  ).textContent = `Something went wrong: ${message}`;
}

function field(key, label, opts) {
  const value = state[key];
  if (opts.radio) {
    return `<fieldset class="sim-field sim-field--wide">
      <legend>${label}</legend>${Object.entries(opts.radio)
        .map(
          ([v, text]) => `<label class="sim-radio"><input type="radio"
            name="${key}" data-key="${key}" value="${v}"
            ${v === value ? "checked" : ""}> ${text}</label>`,
        )
        .join("")}</fieldset>`;
  }
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
          aria-label="Days of work each time through"></td>
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

function loopControls() {
  // The stages repeated until a result is worth writing up
  const options = (key) =>
    state.stages
      .map(
        (s, i) =>
          `<option value="${i}"${i === state[key] ? " selected" : ""}>${escape(
            s.name,
          )}</option>`,
      )
      .join("");
  return `Until a result is worth writing up, repeat from
    <select data-key="loop_from" data-index>${options("loop_from")}</select>
    through
    <select data-key="loop_to" data-index>${options("loop_to")}</select>,
    taking
    <input type="number" data-key="attempts" value="${state.attempts}"
      min="1" step="any" aria-label="Attempts on average">
    attempts on average`;
}

function diagram(id, { policy, calkit = false, interactive = false }) {
  // The workflow as a row of stages: arrows dashed where data is moved
  // between tools by hand, the repeat loop curving back underneath, and
  // PI reviews as gates between steps or a loop over the whole row
  const { stages, attempts, loop_from: from, loop_to: to } = state;
  const NW = 122;
  const NH = 34;
  const GAP = 28;
  const PAD = 14;
  // Room above for the review loop or gate labels, and below for the
  // repeat loop
  const Y = policy === "lean" ? 46 : 22;
  const width = PAD * 2 + stages.length * NW + (stages.length - 1) * GAP;
  const height = Y + NH + (attempts > 1 ? 44 : 6) + 20;
  const x = (i) => PAD + i * (NW + GAP);
  const cx = (i) => x(i) + NW / 2;
  const mid = Y + NH / 2;
  const bottom = Y + NH;
  const short = (name) => (name.length > 17 ? `${name.slice(0, 16)}…` : name);
  const arrow = `url(#${id}-arrow)`;
  const parts = [];
  // Click targets go on top of everything else
  const hits = [];
  if (calkit) {
    parts.push(`<rect class="sim-dag-project" x="${PAD - 7}" y="${Y - 9}"
      width="${width - 2 * PAD + 14}" height="${NH + 18}" rx="9"/>`);
  }
  if (policy === "lean") {
    const top = 16;
    parts.push(`<path class="sim-dag-review" marker-end="${arrow}"
      d="M${cx(stages.length - 1)},${Y - 2} C${cx(stages.length - 1)},${top}
      ${cx(0)},${top} ${cx(0)},${Y - 4}"/>`);
    parts.push(`<text class="sim-dag-note" x="${width / 2}" y="${top + 4}"
      text-anchor="middle">PI review every ${days(
        state.review_interval,
      )} working days${calkit ? ", in the browser" : ""}, while work goes on
      </text>`);
  }
  stages.forEach((stage, i) => {
    parts.push(`<g><title>${escape(stage.name)}</title>
      <rect class="sim-dag-node" x="${x(i)}" y="${Y}" width="${NW}"
        height="${NH}" rx="5"/>
      <text class="sim-dag-label" x="${cx(i)}" y="${mid + 4}"
        text-anchor="middle">${escape(short(stage.name))}</text></g>`);
    if (i === stages.length - 1) return;
    const byHand = stage.hop && !calkit;
    const x1 = x(i) + NW;
    const x2 = x(i + 1) - 1;
    parts.push(`<line class="sim-dag-edge${byHand ? " sim-dag-edge--hand" : ""}"
      x1="${x1}" y1="${mid}" x2="${x2}" y2="${mid}" marker-end="${arrow}"/>`);
    if (interactive) {
      hits.push(`<line class="sim-dag-hit" data-edge="${i}" x1="${x1}"
        y1="${mid}" x2="${x2}" y2="${mid}"><title>${
          byHand ? "Moved by hand" : "Moves on its own"
        }: click to change</title></line>`);
    }
    if (policy === "stage-gate") {
      const gx = (x1 + x2) / 2;
      parts.push(`<line class="sim-dag-gate" x1="${gx}" y1="${mid - 11}"
        x2="${gx}" y2="${mid + 11}"/><text class="sim-dag-note" x="${gx}"
        y="${Y - 4}" text-anchor="middle">PI</text>`);
    }
  });
  if (attempts > 1) {
    const depth = bottom + 34;
    const label = `×${+attempts.toFixed(1)} attempts`;
    if (from === to) {
      parts.push(`<path class="sim-dag-loop" marker-end="${arrow}"
        d="M${cx(to) + 12},${bottom} C${cx(to) + 28},${depth}
        ${cx(to) - 28},${depth} ${cx(to) - 12},${bottom + 2}"/>`);
    } else {
      parts.push(`<path class="sim-dag-loop" marker-end="${arrow}"
        d="M${cx(to)},${bottom} C${cx(to)},${depth} ${cx(from)},${depth}
        ${cx(from)},${bottom + 2}"/>`);
    }
    parts.push(`<text class="sim-dag-note sim-dag-note--loop"
      x="${(cx(from) + cx(to)) / 2}" y="${depth + 9}"
      text-anchor="middle">${label}</text>`);
  }
  const batches =
    policy === "lean"
      ? "One result at a time"
      : `All ${state.n_findings} results through each step together`;
  const tools = calkit
    ? "everything in one Calkit project, checked by CI"
    : "dashed arrows are data moved between tools by hand";
  parts.push(`<text class="sim-dag-note" x="${PAD}" y="${height - 6}"
    >${batches}; ${tools}</text>`);
  return `<svg class="sim-dag" viewBox="0 0 ${width} ${height}" role="img"
    aria-label="${escape(`${batches}; ${tools}`)}">
    <defs><marker id="${id}-arrow" viewBox="0 0 8 8" refX="7" refY="4"
      markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path class="sim-dag-head" d="M0,0 L8,4 L0,8 z"/></marker></defs>
    ${parts.join("")}${hits.join("")}</svg>`;
}

function renderForm() {
  const redraw = () => {
    form.querySelector(".sim-diagram").innerHTML = diagram("form", {
      policy: state.policy,
      interactive: true,
    });
  };
  root.innerHTML = `
    <form class="sim-form" autocomplete="off" data-form-type="other">
      <h2>Your workflow today</h2>
      <div class="sim-diagram"></div>
      <p class="sim-caption">Click an arrow to switch between data moved
        by hand and data that moves on its own.</p>
      <div class="sim-table-wrap"><table class="sim-stages">
        <thead><tr>
          <th>Stage</th><th>Days of work each time through</th>
          <th>Time it takes with AI agents (%)</th>
          <th>Moved to the next stage's tools by hand</th>
          <th>Hours per move</th>
          <th>Moves that get something wrong (%)</th><th></th>
        </tr></thead>
        <tbody>${stageRows()}</tbody>
      </table></div>
      <button type="button" class="md-button sim-add">Add a stage</button>
      <p class="sim-loop">${loopControls()}</p>
      <div class="sim-settings">${SETTINGS.map(([k, label, opts]) =>
        field(k, label, opts),
      ).join("")}</div>
      <button type="submit" class="md-button md-button--primary sim-run">
        Simulate</button>
      <span class="sim-status"></span>
      <progress class="sim-progress" max="1" value="0" hidden></progress>
      <p class="sim-caption">Simulations run in your browser, in Python, with
        Pyodide. See <a href="${SOURCE}/blob/main/docs/simulator/research_flow.py">the
        model</a> and
        <a href="${SOURCE}/tree/main/docs/simulator">the rest of this page's source</a> on
        GitHub.</p>
    </form>
    <div class="sim-results"></div>
    <div class="sim-tip" role="tooltip" hidden></div>`;
  const form = root.querySelector("form");
  redraw();
  form.addEventListener("input", (event) => {
    const t = event.target;
    if (t.dataset.key) {
      state[t.dataset.key] =
        t.type === "checkbox"
          ? t.checked
          : t.type === "radio" ||
            (t.tagName === "SELECT" && !("index" in t.dataset))
          ? t.value
          : +t.value;
      // The loop can't end before it starts
      if (t.dataset.key === "loop_from" || t.dataset.key === "loop_to") {
        if (state.loop_to < state.loop_from) {
          state.loop_from = state.loop_to = +t.value;
        }
        form.querySelector(".sim-loop").innerHTML = loopControls();
      }
    } else if (t.dataset.stage) {
      const stage = state.stages[+t.dataset.stage];
      const f = t.dataset.field;
      stage[f] =
        t.type === "checkbox" ? t.checked : f === "name" ? t.value : +t.value;
      if (PERCENT.includes(f)) stage[f] /= 100;
      if (f === "name") {
        form.querySelector(".sim-loop").innerHTML = loopControls();
      }
      if (f === "hop") {
        for (const g of ["hop_hours", "hop_error"]) {
          form.querySelector(
            `[data-stage="${t.dataset.stage}"][data-field="${g}"]`,
          ).disabled = !t.checked;
        }
      }
    }
    redraw();
  });
  form.addEventListener("click", (event) => {
    const remove = event.target.closest("[data-remove]");
    const edge = event.target.closest("[data-edge]");
    if (event.target.closest(".sim-add")) {
      state.stages.push({
        ...state.new_stage,
        name: `stage ${state.stages.length + 1}`,
      });
    } else if (remove) {
      const i = +remove.dataset.remove;
      state.stages.splice(i, 1);
      // The loop keeps its stages when one before them goes
      if (i < state.loop_from) state.loop_from--;
      if (i < state.loop_to) state.loop_to--;
    } else if (edge) {
      const stage = state.stages[+edge.dataset.edge];
      stage.hop = !stage.hop;
    } else {
      return;
    }
    const last = state.stages.length - 1;
    state.loop_from = Math.min(state.loop_from, last);
    state.loop_to = Math.min(state.loop_to, last);
    form.querySelector("tbody").innerHTML = stageRows();
    form.querySelector(".sim-loop").innerHTML = loopControls();
    redraw();
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
  const flawed = (c) =>
    `${c.flawed.toFixed(1)} flawed results published, vs
    ${today.flawed.toFixed(1)}`;
  const saving = (c, label = c.name) => ({
    label,
    value: c.saved,
    low: c.low,
    high: c.high,
    tip:
      `${days(c.saved)} working days saved per paper ` +
      `(95% interval ${days(c.low)} to ${days(c.high)}): ` +
      `${days(c.days)} to a published paper instead of ` +
      `${days(today.days)}; ${flawed(c)} today`,
  });
  const cell = (id, title, policy, calkit, c, note) => `<div class="sim-cell">
      <span class="sim-tile-label">${title}</span>
      <div class="sim-diagram">${diagram(id, { policy, calkit })}</div>
      <span class="sim-tile-value">${days(c.days)}</span>
      <span class="sim-tile-note">${note}</span></div>`;
  const faster = (c) =>
    `${c.ratio.toFixed(2)}× as fast as today; ${flawed(c)} today`;
  const policy = report.split ? "stage-gate" : "lean";
  // Where Calkit's savings come from, which add up only roughly
  let sources = `All ${days(first.saved)} days saved come from connecting
    your tools in one project, since you already work in small batches.`;
  if (report.split) {
    const { batches, project, together } = report.split;
    const extra =
      together >= 0
        ? `${days(together)} more than they save apart`
        : `${days(-together)} less than they save apart`;
    sources = `Of the ${days(first.saved)} days saved, about
      ${days(batches)} come from smaller batches and ${days(project)} from
      connecting your tools in one project. Together they save ${extra},
      which is split evenly between them here.`;
  }
  const cells = [
    cell(
      "today",
      "Status quo: large batches, manual data transfer between tools",
      policy,
      false,
      today,
      `${months(today.days)} months; 80% of runs
      ${days(today.p10)}–${days(today.p90)};
      ${today.flawed.toFixed(1)} flawed results published`,
    ),
    cell(
      "calkit",
      "Calkit: small batches, connected tools in one project",
      "lean",
      true,
      first,
      `${faster(first)}; includes ${days(first.learning_days)} days learning
      Calkit, and later papers take ${days(later.days)}. ${sources}`,
    ),
  ];
  const parts = report.parts.map((c) => saving(c));
  const adding = report.agents.map((c) => saving(c));
  // One scale for both, so Calkit's parts compare with what agents do
  const scale = extent([...parts, ...adding]);
  const breakdown = Object.entries(today.breakdown).map(([k, v]) => ({
    label: capitalize(k),
    value: v,
    tip: `${days(v)} working days, ${Math.round((v / today.days) * 100)}%`,
  }));
  const unfinished = today.unfinished + first.unfinished + later.unfinished;
  const agents = report.uses_agents ? ", with AI agents" : "";
  root.querySelector(".sim-results").innerHTML = `
    <h2>Working days to a published paper${agents}</h2>
    <div class="sim-cells">${cells.join("")}</div>
    ${
      unfinished
        ? `<p class="sim-warning">${unfinished} runs hadn't published
          after 5,000 working days and were cut off there.</p>`
        : ""
    }
    <h2>What each part of Calkit saves</h2>
    <p class="sim-caption">Working days saved per paper by each part of
      Calkit added to how you work today on its own, with 95% intervals,
      from ${report.reps} runs each. Hover for flawed results published.</p>
    ${bars(parts, scale)}
    ${
      adding.length
        ? `<h2>Adding AI agents</h2>
          <p class="sim-caption">Working days saved per paper by adding AI
            agents to how you work today, alone and with Calkit, on the same
            scale as Calkit's parts above.</p>
          ${bars(adding, scale)}`
        : ""
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
    // The workflow's shape, never what was typed into it
    track("event", "simulator_run", {
      stages: inputs.stages.length,
      hops_by_hand: inputs.stages.filter((s) => s.hop).length,
      policy: inputs.policy,
      agents: inputs.agents,
      attempts: inputs.attempts,
      seconds: Number(seconds),
    });
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
