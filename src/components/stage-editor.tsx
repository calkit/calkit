import React from "react";
import { Dialog, ReactWidget } from "@jupyterlab/apputils";

export interface StageEditorResult {
  name: string;
  kind: string;
  environment: string;
  inputs: string[];
  outputs: string[];
  attributes: Record<string, any>;
}

export interface StageEditorOptions {
  title: string;
  stageName?: string;
  kind?: string;
  environment?: string;
  inputs?: string[];
  outputs?: string[];
  attributes?: Record<string, any>;
  onSave: (result: StageEditorResult) => Promise<void>;
}

export const STAGE_KIND_OPTIONS = [
  { value: "jupyter-notebook", label: "Jupyter notebook" },
  { value: "python-script", label: "Python script" },
  { value: "r-script", label: "R script" },
  { value: "matlab-script", label: "MATLAB script" },
  { value: "matlab-command", label: "MATLAB command" },
  { value: "shell-command", label: "Shell command" },
  { value: "shell-script", label: "Shell script" },
  { value: "docker-command", label: "Docker command" },
  { value: "latex", label: "LaTeX" },
  { value: "json-to-latex", label: "JSON to LaTeX" },
  { value: "word-to-pdf", label: "Word to PDF" },
  { value: "julia-script", label: "Julia script" },
  { value: "julia-command", label: "Julia command" },
  { value: "sbatch", label: "Slurm batch" },
  { value: "map-paths", label: "Map paths" },
];

interface StageField {
  name: string;
  label: string;
  type: "text" | "list" | "select" | "boolean" | "json";
  placeholder?: string;
  options?: { value: string; label: string }[];
}

const STAGE_KIND_FIELDS: Record<string, StageField[]> = {
  "python-script": [
    {
      name: "script_path",
      label: "Script path",
      type: "text",
      placeholder: "scripts/run.py",
    },
    { name: "args", label: "Args", type: "list", placeholder: "--flag value" },
  ],
  "r-script": [
    {
      name: "script_path",
      label: "Script path",
      type: "text",
      placeholder: "scripts/run.R",
    },
    { name: "args", label: "Args", type: "list", placeholder: "--flag value" },
  ],
  "matlab-script": [
    {
      name: "script_path",
      label: "Script path",
      type: "text",
      placeholder: "scripts/run.m",
    },
  ],
  "matlab-command": [
    {
      name: "command",
      label: "MATLAB command",
      type: "text",
      placeholder: "disp('hi')",
    },
  ],
  "shell-command": [
    {
      name: "command",
      label: "Shell command",
      type: "text",
      placeholder: "echo hello",
    },
    {
      name: "shell",
      label: "Shell",
      type: "select",
      options: [
        { value: "bash", label: "bash" },
        { value: "sh", label: "sh" },
        { value: "zsh", label: "zsh" },
      ],
    },
  ],
  "shell-script": [
    {
      name: "script_path",
      label: "Script path",
      type: "text",
      placeholder: "scripts/run.sh",
    },
    { name: "args", label: "Args", type: "list", placeholder: "--flag value" },
    {
      name: "shell",
      label: "Shell",
      type: "select",
      options: [
        { value: "bash", label: "bash" },
        { value: "sh", label: "sh" },
        { value: "zsh", label: "zsh" },
      ],
    },
  ],
  "docker-command": [
    {
      name: "command",
      label: "Docker command",
      type: "text",
      placeholder: "docker run ...",
    },
  ],
  latex: [
    {
      name: "target_path",
      label: "Target .tex",
      type: "text",
      placeholder: "paper/main.tex",
    },
    {
      name: "latexmkrc_path",
      label: "latexmkrc path",
      type: "text",
      placeholder: "latexmkrc",
    },
    { name: "verbose", label: "Verbose", type: "boolean" },
    { name: "force", label: "Force", type: "boolean" },
    { name: "synctex", label: "Synctex", type: "boolean" },
  ],
  "json-to-latex": [
    { name: "command_name", label: "Command name", type: "text" },
    {
      name: "format",
      label: "Format (JSON)",
      type: "json",
      placeholder: '{\n  "section": "value"\n}',
    },
  ],
  "word-to-pdf": [
    {
      name: "word_doc_path",
      label: "Word doc path",
      type: "text",
      placeholder: "report.docx",
    },
  ],
  "julia-script": [
    {
      name: "script_path",
      label: "Script path",
      type: "text",
      placeholder: "scripts/run.jl",
    },
    { name: "args", label: "Args", type: "list", placeholder: "--flag value" },
  ],
  "julia-command": [
    {
      name: "command",
      label: "Julia command",
      type: "text",
      placeholder: 'println("hi")',
    },
  ],
  sbatch: [
    {
      name: "script_path",
      label: "Script path",
      type: "text",
      placeholder: "scripts/job.sh",
    },
    { name: "args", label: "Args", type: "list", placeholder: "--flag value" },
    {
      name: "sbatch_options",
      label: "sbatch options",
      type: "list",
      placeholder: "--gres=gpu:1",
    },
    {
      name: "log_storage",
      label: "Log storage",
      type: "select",
      options: [
        { value: "git", label: "Git" },
        { value: "dvc", label: "DVC" },
      ],
    },
  ],
  "jupyter-notebook": [
    {
      name: "notebook_path",
      label: "Notebook path",
      type: "text",
      placeholder: "notebooks/run.ipynb",
    },
    {
      name: "cleaned_ipynb_storage",
      label: "Cleaned notebook storage",
      type: "select",
      options: [
        { value: "git", label: "Git" },
        { value: "dvc", label: "DVC" },
        { value: "", label: "Unset" },
      ],
    },
    {
      name: "executed_ipynb_storage",
      label: "Executed notebook storage",
      type: "select",
      options: [
        { value: "dvc", label: "DVC" },
        { value: "git", label: "Git" },
        { value: "", label: "Unset" },
      ],
    },
    {
      name: "html_storage",
      label: "HTML storage",
      type: "select",
      options: [
        { value: "dvc", label: "DVC" },
        { value: "git", label: "Git" },
        { value: "", label: "Unset" },
      ],
    },
    {
      name: "language",
      label: "Notebook language",
      type: "select",
      options: [
        { value: "python", label: "Python" },
        { value: "matlab", label: "MATLAB" },
        { value: "julia", label: "Julia" },
      ],
    },
    {
      name: "parameters",
      label: "Parameters (JSON)",
      type: "json",
      placeholder: '{\n  "param": 1\n}',
    },
  ],
  "map-paths": [
    {
      name: "paths",
      label: "Paths (JSON)",
      type: "json",
      placeholder:
        '[{\n  "kind": "file-to-file",\n  "src": "input.txt",\n  "dest": "out.txt"\n}]',
    },
  ],
};

interface StageEditorBodyProps {
  initialName?: string;
  initialKind: string;
  initialEnvironment?: string;
  initialInputs: string[];
  initialOutputs: string[];
  initialAttributes?: Record<string, any>;
  nameEditable: boolean;
  onChange: (state: {
    name: string;
    kind: string;
    environment: string;
    inputs: string[];
    outputs: string[];
    fieldValues: Record<string, any>;
    additionalJson: string;
  }) => void;
}

const StageEditorBody: React.FC<StageEditorBodyProps> = ({
  initialName = "",
  initialKind,
  initialEnvironment = "",
  initialInputs,
  initialOutputs,
  initialAttributes = {},
  nameEditable,
  onChange,
}) => {
  const [name, setName] = React.useState(initialName);
  const [kind, setKind] = React.useState(initialKind);
  const [environment, setEnvironment] = React.useState(initialEnvironment);
  const [inputs, setInputs] = React.useState<string[]>(initialInputs);
  const [outputs, setOutputs] = React.useState<string[]>(initialOutputs);

  const kindFields = STAGE_KIND_FIELDS[kind] || [];

  const initFieldValues = React.useMemo(() => {
    const defaults: Record<string, any> = {};
    for (const field of STAGE_KIND_FIELDS[initialKind] || []) {
      if (initialAttributes[field.name] !== undefined) {
        defaults[field.name] = initialAttributes[field.name];
      } else if (field.type === "list") {
        defaults[field.name] = [];
      } else if (field.type === "boolean") {
        defaults[field.name] = false;
      } else if (field.type === "select" && field.options?.length) {
        defaults[field.name] = field.options[0].value;
      } else {
        defaults[field.name] = "";
      }
    }
    return defaults;
  }, [initialAttributes, initialKind]);

  const [fieldValues, setFieldValues] =
    React.useState<Record<string, any>>(initFieldValues);
  const [additionalJson, setAdditionalJson] = React.useState(
    JSON.stringify(initialAttributes, null, 2),
  );

  React.useEffect(() => {
    onChange({
      name,
      kind,
      environment,
      inputs,
      outputs,
      fieldValues,
      additionalJson,
    });
  }, [
    name,
    kind,
    environment,
    inputs,
    outputs,
    fieldValues,
    additionalJson,
    onChange,
  ]);

  React.useEffect(() => {
    // Reset kind-specific fields when kind changes
    const defaults: Record<string, any> = {};
    for (const field of STAGE_KIND_FIELDS[kind] || []) {
      const existing = fieldValues[field.name];
      if (existing !== undefined) {
        defaults[field.name] = existing;
      } else if (field.type === "list") {
        defaults[field.name] = [];
      } else if (field.type === "boolean") {
        defaults[field.name] = false;
      } else if (field.type === "select" && field.options?.length) {
        defaults[field.name] = field.options[0].value;
      } else {
        defaults[field.name] = "";
      }
    }
    setFieldValues(defaults);
  }, [kind]);

  const addListValue = (
    current: string[],
    setFn: React.Dispatch<React.SetStateAction<string[]>>,
    value: string,
  ) => {
    const trimmed = value.trim();
    if (!trimmed) return;
    setFn([...current, trimmed]);
  };

  const renderList = (
    items: string[],
    setFn: (updater: string[] | ((prev: string[]) => string[])) => void,
    placeholder: string,
  ) => {
    const inputRef = React.createRef<HTMLInputElement>();
    return (
      <div className="calkit-stage-io-list">
        {items.length === 0 ? (
          <div className="calkit-stage-io-empty">No items</div>
        ) : (
          items.map((item, index) => (
            <div key={index} className="calkit-stage-io-item">
              <span>{item}</span>
              <button
                className="calkit-stage-io-remove"
                onClick={() => {
                  setFn(items.filter((_, i) => i !== index));
                }}
              >
                ×
              </button>
            </div>
          ))
        )}
        <div className="calkit-stage-io-input-container">
          <input
            ref={inputRef}
            type="text"
            placeholder={placeholder}
            onKeyPress={(e) => {
              if (e.key === "Enter") {
                const val = inputRef.current?.value || "";
                addListValue(items, setFn, val);
                if (inputRef.current) inputRef.current.value = "";
              }
            }}
            autoComplete="off"
          />
          <button
            className="calkit-stage-io-add-button"
            onClick={() => {
              const val = inputRef.current?.value || "";
              addListValue(items, setFn, val);
              if (inputRef.current) inputRef.current.value = "";
            }}
          >
            Add
          </button>
        </div>
      </div>
    );
  };

  const renderField = (field: StageField) => {
    const value = fieldValues[field.name];
    const setValue = (val: any) => {
      setFieldValues((prev) => ({ ...prev, [field.name]: val }));
    };

    if (field.type === "text") {
      return (
        <div key={field.name} className="calkit-stage-editor-field">
          <label>{field.label}</label>
          <input
            type="text"
            value={value ?? ""}
            placeholder={field.placeholder}
            onChange={(e) => setValue(e.target.value)}
            autoComplete="off"
          />
        </div>
      );
    }

    if (field.type === "list") {
      const listValue: string[] = Array.isArray(value) ? value : [];
      const setListValue = (val: string[] | ((prev: string[]) => string[])) => {
        if (typeof val === "function") {
          setValue(val(listValue));
        } else {
          setValue(val);
        }
      };
      return (
        <div key={field.name} className="calkit-stage-editor-field">
          <label>{field.label}</label>
          {renderList(listValue, setListValue, field.placeholder || "value")}
        </div>
      );
    }

    if (field.type === "select") {
      return (
        <div key={field.name} className="calkit-stage-editor-field">
          <label>{field.label}</label>
          <select
            value={value ?? ""}
            onChange={(e) => setValue(e.target.value)}
          >
            {(field.options || []).map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>
      );
    }

    if (field.type === "boolean") {
      return (
        <div key={field.name} className="calkit-stage-editor-field">
          <label>{field.label}</label>
          <input
            type="checkbox"
            checked={!!value}
            onChange={(e) => setValue(e.target.checked)}
          />
        </div>
      );
    }

    if (field.type === "json") {
      return (
        <div key={field.name} className="calkit-stage-editor-field">
          <label>{field.label}</label>
          <textarea
            rows={4}
            value={
              typeof value === "string"
                ? value
                : JSON.stringify(value || {}, null, 2)
            }
            placeholder={field.placeholder}
            onChange={(e) => setValue(e.target.value)}
            autoComplete="off"
          />
        </div>
      );
    }

    return null;
  };

  return (
    <div className="calkit-stage-editor">
      <div className="calkit-stage-editor-field">
        <label>Stage name</label>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g., process_data"
          autoFocus
          disabled={!nameEditable}
          autoComplete="off"
        />
      </div>

      <div className="calkit-stage-editor-field">
        <label>Stage kind</label>
        <select value={kind} onChange={(e) => setKind(e.target.value)}>
          {STAGE_KIND_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </div>

      <div className="calkit-stage-editor-field">
        <label>Environment</label>
        <input
          type="text"
          value={environment}
          onChange={(e) => setEnvironment(e.target.value)}
          placeholder="environment name"
          autoComplete="off"
        />
      </div>

      <div className="calkit-stage-editor-field">
        <label>Inputs</label>
        {renderList(inputs, setInputs, "path/to/input")}
      </div>

      <div className="calkit-stage-editor-field">
        <label>Outputs</label>
        {renderList(outputs, setOutputs, "path/to/output")}
      </div>

      {kindFields.map((field) => renderField(field))}

      <div className="calkit-stage-editor-field">
        <label>Additional attributes (JSON)</label>
        <textarea
          rows={4}
          value={additionalJson}
          onChange={(e) => setAdditionalJson(e.target.value)}
          placeholder='{"custom": true}'
          autoComplete="off"
        />
      </div>
    </div>
  );
};

export async function showStageEditorDialog(
  options: StageEditorOptions,
): Promise<void> {
  const {
    title,
    stageName,
    kind,
    environment,
    inputs = [],
    outputs = [],
    attributes = {},
    onSave,
  } = options;

  const nameEditable = stageName === undefined;
  const initialKind = kind || STAGE_KIND_OPTIONS[0].value;

  let formState: {
    name: string;
    kind: string;
    environment: string;
    inputs: string[];
    outputs: string[];
    fieldValues: Record<string, any>;
    additionalJson: string;
  } = {
    name: stageName || "",
    kind: initialKind,
    environment: environment || "",
    inputs,
    outputs,
    fieldValues: {},
    additionalJson: JSON.stringify(attributes, null, 2),
  };

  const body = ReactWidget.create(
    <StageEditorBody
      initialName={stageName}
      initialKind={initialKind}
      initialEnvironment={environment}
      initialInputs={inputs}
      initialOutputs={outputs}
      initialAttributes={attributes}
      nameEditable={nameEditable}
      onChange={(state) => {
        formState = state;
      }}
    />,
  );

  const res = await new Dialog({
    title,
    body,
    buttons: [
      Dialog.cancelButton(),
      Dialog.okButton({ label: stageName ? "Save" : "Create" }),
    ],
  }).launch();

  if (!res.button.accept) return;

  const trimmedName = formState.name?.trim();
  if (!trimmedName) return;

  let additionalAttrs: Record<string, any> = {};
  const additionalText = formState.additionalJson || "";
  if (additionalText.trim()) {
    try {
      additionalAttrs = JSON.parse(additionalText);
    } catch (err) {
      console.error("Invalid additional attributes JSON:", err);
      return;
    }
  }

  const attributesMerged: Record<string, any> = {
    ...additionalAttrs,
  };
  for (const [key, value] of Object.entries(formState.fieldValues || {})) {
    // If the value is a JSON string for json fields, attempt to parse
    if (
      typeof value === "string" &&
      (value.trim().startsWith("{") || value.trim().startsWith("["))
    ) {
      try {
        attributesMerged[key] = JSON.parse(value);
        continue;
      } catch {
        // fall through to raw string
      }
    }
    attributesMerged[key] = value;
  }

  await onSave({
    name: trimmedName,
    kind: formState.kind,
    environment: formState.environment || "",
    inputs: formState.inputs,
    outputs: formState.outputs,
    attributes: attributesMerged,
  });
}
