// These selectors are mounted by HA's ha-selector inside its normal forms.
// They only register Grenton elements; no stock frontend elements are modified.
const STYLE = `
  :host { display: block; color: var(--primary-text-color); }
  * { box-sizing: border-box; }
  .fields, .arguments { display: grid; gap: 16px; }
  label { display: grid; gap: 6px; min-width: 0; font-size: 14px; }
  input, select, textarea, button {
    font: inherit; color: var(--primary-text-color, #202124);
    background: var(--card-background-color, white);
    border: 1px solid var(--divider-color, #aaa); border-radius: 6px;
  }
  input, select, textarea { width: 100%; min-height: 42px; padding: 10px; }
  input[type=checkbox] { width: 24px; height: 24px; min-height: 24px; }
  textarea { min-height: 72px; resize: vertical; }
  button { padding: 8px 12px; cursor: pointer; }
  button:hover { background: var(--secondary-background-color, #f5f5f5); }
  button:disabled { opacity: .5; cursor: default; }
  :is(input, select, textarea, button):focus-visible {
    outline: 2px solid var(--primary-color, #03a9f4); outline-offset: 2px;
  }
  .argument { border: 1px solid var(--divider-color, #ddd); border-radius: 8px; padding: 12px; }
  .heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 12px; }
  .heading strong { font-size: 14px; }
  .buttons { display: flex; gap: 6px; }
  .inputs { display: grid; grid-template-columns: minmax(100px, 1fr) minmax(140px, 2fr); gap: 12px; }
  .schedule-periods { display: grid; gap: 8px; margin: 12px 0 8px; }
  .schedule-period-row { display: grid; align-items: center;
    grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr) 42px; gap: 8px; }
  .schedule-period-headings { align-items: end; font-size: 14px; }
  .schedule-time { border: 0; padding: 0; margin: 0; min-width: 0;
    display: grid; align-items: center;
    grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr); gap: 4px; }
  .schedule-period-row input, .schedule-period-row select {
    height: 42px; min-width: 0; padding: 8px; }
  .schedule-time select { padding-inline: 4px; }
  .schedule-period-remove { width: 42px; height: 42px; padding: 0; font-size: 22px; }
  .hint { font-size: 13px; color: var(--secondary-text-color, #666); margin: 0; }
  .add { justify-self: start; color: var(--primary-color, #03a9f4); }
  .arguments { margin-top: 16px; }
  @media (max-width: 400px) { .inputs { grid-template-columns: 1fr; } }
`;

const copy = (value) => value === undefined ? undefined : structuredClone(value);
const argumentRows = (rows) => rows?.map((row) => {
  if (!row?.argument) return row;
  const type = row.argument.active_choice;
  return { type, value: type === "nil" ? null : row.argument[type] };
});
const TYPES = ["string", "number", "float", "boolean", "nil", "lua"];
const CALL_TYPES = ["SCRIPT", "METHOD", "ATTRIBUTE", "VARIABLE"];

class GrentonEditor extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._disabled = false;
    // HA can set properties before the extra module has finished loading.
    // Replay those own properties through the setters when upgrading the tag.
    for (const name of ["hass", "selector", "value", "localizeValue", "disabled"]) {
      if (Object.prototype.hasOwnProperty.call(this, name)) {
        const value = this[name];
        delete this[name];
        this[name] = value;
      }
    }
  }

  set hass(value) {
    const previousLanguage = this._hass?.language;
    this._hass = value;
    if (previousLanguage !== value?.language) this._scheduleRender();
  }
  get hass() { return this._hass; }
  set selector(value) {
    if (JSON.stringify(value) === JSON.stringify(this._selector)) return;
    this._selector = value;
    this._scheduleRender();
  }
  get selector() { return this._selector; }
  set value(value) {
    value = this._prepareValue(value);
    if (JSON.stringify(value) === JSON.stringify(this._value)) return;
    this._value = copy(value);
    this._scheduleRender();
  }
  get value() { return copy(this._value); }
  _prepareValue(value) { return value; }
  set localizeValue(value) {
    if (value === this._localizeValue) return;
    this._localizeValue = value;
    this._scheduleRender();
  }
  set disabled(value) {
    if (value === this._disabled) return;
    this._disabled = value;
    this._scheduleRender();
  }
  get disabled() { return this._disabled; }

  connectedCallback() { this._scheduleRender(); }

  _scheduleRender() {
    if (this._renderPending) return;
    this._renderPending = true;
    queueMicrotask(() => {
      this._renderPending = false;
      if (this.isConnected) this._render();
    });
  }

  _text(key, fallback) {
    return this._localizeValue?.(key) || fallback;
  }

  _label(name, fallback) {
    return this._text(`scene_editor.fields.${name}.name`, fallback);
  }

  _emit() {
    this.dispatchEvent(new CustomEvent("value-changed", {
      detail: { value: this.value }, bubbles: true, composed: true,
    }));
  }

  _container() {
    this.shadowRoot.replaceChildren();
    const style = document.createElement("style");
    style.textContent = STYLE;
    const content = document.createElement("div");
    content.className = "fields";
    this.shadowRoot.append(style, content);
    return content;
  }

  _input(name, value, onChange, type = "text", required = true) {
    const control = document.createElement(type === "lua" ? "textarea" : "input");
    control.dataset.field = name;
    if (type !== "lua") control.type = type;
    if (type === "number") control.step = "any";
    if (type === "checkbox") control.checked = value === true;
    else control.value = value ?? "";
    control.required = required && type !== "checkbox";
    control.disabled = this.disabled;
    control.addEventListener("input", () => {
      const next = type === "checkbox" ? control.checked
        : type === "number" && control.value !== "" && !control.validity.badInput
          ? control.valueAsNumber : control.value;
      onChange(next);
      this._emit();
    });
    return control;
  }

  _select(name, options, value, onChange) {
    const control = document.createElement("select");
    control.dataset.field = name;
    control.required = true;
    control.disabled = this.disabled;
    // Keep an unselected field empty until the user makes a real selection.
    if (!options.some((option) => option.value === value)) {
      const empty = document.createElement("option");
      empty.value = "";
      empty.textContent = "—";
      control.append(empty);
    }
    for (const item of options) {
      const option = document.createElement("option");
      option.value = item.value;
      option.textContent = item.label;
      control.append(option);
    }
    control.value = value ?? "";
    control.addEventListener("change", () => {
      onChange(control.value);
      this._emit();
      if (!control.isConnected) {
        this.shadowRoot.querySelector(`select[data-field="${name}"]`)?.focus();
      }
    });
    return control;
  }

  _field(labelText, control) {
    const label = document.createElement("label");
    const caption = document.createElement("span");
    caption.textContent = labelText;
    label.append(caption, control);
    return label;
  }

  _button(text, action, disabled = false, title = text) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = text;
    button.title = title;
    button.setAttribute("aria-label", title);
    button.disabled = disabled || this.disabled;
    button.addEventListener("click", action);
    return button;
  }

  _renderArguments(parent, rows, onRowsChange) {
    const argumentsContainer = document.createElement("div");
    argumentsContainer.className = "arguments";
    const changeRows = (next) => {
      onRowsChange(next);
      this._emit();
      this._render();
    };
    const hint = document.createElement("p");
    hint.className = "hint";
    hint.textContent = this._text("scene_editor.fields.arguments.description",
      "Omit trailing arguments to use the script or method defaults.");
    argumentsContainer.append(hint);
    rows.forEach((argument, index) => {
      const row = document.createElement("div");
      row.className = "argument";
      row.dataset.argument = index;
      const heading = document.createElement("div");
      heading.className = "heading";
      const title = document.createElement("strong");
      title.textContent = `${this._label("argument", "Argument")} ${index + 1}`;
      const buttons = document.createElement("div");
      buttons.className = "buttons";
      const move = (offset) => {
        const next = copy(rows);
        [next[index], next[index + offset]] = [next[index + offset], next[index]];
        changeRows(next);
      };
      buttons.append(
        this._button("↑", () => move(-1), index === 0, this._label("move_up", "Move up")),
        this._button("↓", () => move(1), index === rows.length - 1, this._label("move_down", "Move down")),
        this._button(this._label("remove", "Remove"), () => changeRows(rows.filter((_, i) => i !== index))),
      );
      heading.append(title, buttons);
      const inputs = document.createElement("div");
      inputs.className = "inputs";
      const type = this._select(`argument_${index}_type`, TYPES.map((value) => ({
        value, label: this._text(`scene_argument_types.choices.${value}`, value),
      })), argument.type, (value) => {
        argument.type = value;
        argument.value = value === "nil" ? null : value === "boolean" ? false
          : value === "number" || value === "float" ? 0 : "";
        onRowsChange(rows);
        this._render();
      });
      const input = this._input(`argument_${index}_value`,
        argument.type === "nil" ? "nil" : argument.value,
        (value) => { argument.value = value; onRowsChange(rows); },
        argument.type === "boolean" ? "checkbox"
          : argument.type === "number" || argument.type === "float" ? "number"
          : argument.type === "lua" ? "lua" : "text", argument.type !== "string");
      if (argument.type === "nil") input.disabled = true;
      inputs.append(
        this._field(this._label("argument_type", "Type"), type),
        this._field(this._label("argument_value", "Value"), input),
      );
      row.append(heading, inputs);
      argumentsContainer.append(row);
    });
    const add = this._button(this._label("add_argument", "Add argument"), () => {
      changeRows([...rows, { type: "string", value: "" }]);
      const inputs = this.shadowRoot.querySelectorAll(".argument input:not([disabled])");
      inputs[inputs.length - 1]?.focus();
    });
    add.className = "add";
    argumentsContainer.append(add);
    parent.append(argumentsContainer);
  }

  reportValidity() {
    for (const control of this.shadowRoot.querySelectorAll("input, select, textarea")) {
      if (!control.reportValidity()) return false;
    }
    return true;
  }

  focus() {
    (this.shadowRoot.querySelector(":invalid") ||
      this.shadowRoot.querySelector("select, input, textarea, button"))?.focus();
  }
}

class GrentonSceneEditor extends GrentonEditor {
  _prepareValue(value) {
    return value ? { ...value, arguments: argumentRows(value.arguments) } : value;
  }
  _render() {
    const parent = this._container();
    const draft = this._value ?? {};
    const type = draft.call_type ?? "";
    const settings = this.selector?.grenton_scene ?? {};
    const state = settings.mode === "state";
    const callTypes = state ? ["ATTRIBUTE", "VARIABLE"] : CALL_TYPES;
    const control = (name, label, value = draft[name]) => this._field(
      this._label(name, label),
      this._input(name, value, (next) => { this._value = { ...this._value, [name]: next }; }),
    );
    parent.append(this._field(this._label(state ? "state_call_type" : "call_type",
      state ? "State source type" : "Action call type"), this._select(
      "call_type", callTypes.map((value) => ({
        value, label: this._text(`scene_call_types.options.${value}`, value),
      })), type, (value) => {
        this._value = { ...this._value, call_type: value };
        this._render();
      },
    )));
    parent.append(this._field(this._label("clu_id", "CLU"), this._select(
      "clu_id", settings.clus ?? [], draft.clu_id,
      (value) => { this._value = { ...this._value, clu_id: value }; },
    )));
    if (!callTypes.includes(type)) return;
    const renderValue = () => {
      if (!state && settings.editable_value) {
        parent.append(this._field(this._label("set_value", "Value to set"),
          this._input("value", draft.value,
            (value) => { this._value = { ...this._value, value }; }, "text", false)));
      }
    };
    if (type === "VARIABLE") {
      parent.append(control("variable_name", "Variable name", draft.variable_name));
      renderValue();
      return;
    }
    parent.append(this._field(this._label(type === "SCRIPT" ? "script_name" : "object_name",
      type === "SCRIPT" ? "Script name" : "Object name"),
      this._input("object_name", draft.object_name,
        (value) => { this._value = { ...this._value, object_name: value }; })));
    if (type !== "SCRIPT") {
      parent.append(this._field(this._label(type === "METHOD" ? "method_index" : "attribute_index",
        type === "METHOD" ? "Method index" : "Attribute index"),
        this._input("index", draft.index, (value) => { this._value = { ...this._value, index: value }; })));
    }
    if (type === "SCRIPT" || type === "METHOD") {
      this._renderArguments(parent, draft.arguments ?? [],
        (rows) => { this._value = { ...this._value, arguments: rows }; });
    }
    if (type === "ATTRIBUTE") renderValue();
  }
}

class GrentonArgumentsEditor extends GrentonEditor {
  _prepareValue(value) { return argumentRows(value); }
  _render() {
    const parent = this._container();
    const label = document.createElement("strong");
    label.textContent = this.label || this._label("arguments", "Arguments");
    parent.append(label);
    this._renderArguments(parent, this._value ?? [],
      (rows) => { this._value = rows; });
  }
}

class GrentonEntityPicker extends GrentonEditor {
  set hass(value) {
    super.hass = value;
    if (this._picker) this._picker.hass = value;
  }
  get hass() { return super.hass; }

  _render() {
    const parent = this._container();
    const entities = this.selector?.grenton_entity?.include_entities || [];
    const domains = [...new Set(entities.map((id) => id.split(".")[0]))].sort();
    if (!domains.includes(this._domainFilter)) this._domainFilter = "all";
    const options = [
      { value: "all", label: this._text("entity_picker.types.all", "All entities") },
      ...domains.map((domain) => ({
        value: domain,
        label: this._text(`entity_picker.types.${domain}`, domain),
      })),
    ];
    const filter = this._select("entity_type", options, this._domainFilter, (domain) => {
      this._domainFilter = domain;
      // A hidden selection must not be submitted accidentally.
      if (this._value && domain !== "all" && !this._value.startsWith(`${domain}.`)) {
        this._value = undefined;
      }
      this._render();
    });
    parent.append(this._field(this._text("entity_picker.fields.entity_type", "Entity type"), filter));

    const visible = entities.filter((id) => this._domainFilter === "all" || id.startsWith(`${this._domainFilter}.`));
    const picker = document.createElement("ha-selector");
    this._picker = picker;
    picker.dataset.field = "entity";
    picker.hass = this.hass;
    picker.label = this._text("entity_picker.fields.entity", "Entity");
    picker.selector = { entity: { include_entities: visible, multiple: false } };
    picker.value = this._value;
    picker.disabled = this.disabled;
    picker.required = true;
    picker.addEventListener("value-changed", (event) => {
      event.stopPropagation();
      if (this.disabled) return;
      const value = event.detail.value || undefined;
      if (value !== undefined && !visible.includes(value)) return;
      this._value = value;
      this._emit();
    });
    parent.append(picker);
  }
}

if (!customElements.get("ha-selector-grenton_entity")) {
  customElements.define("ha-selector-grenton_entity", GrentonEntityPicker);
}

if (!customElements.get("ha-selector-grenton_scene")) {
  customElements.define("ha-selector-grenton_scene", GrentonSceneEditor);
}
if (!customElements.get("ha-selector-grenton_arguments")) {
  customElements.define("ha-selector-grenton_arguments", GrentonArgumentsEditor);
}

const WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"];

class GrentonThermostatEditor extends GrentonEditor {
  _label(name, fallback) {
    return this._text(`thermostat_editor.fields.${name}.name`, fallback);
  }

  _change(action) {
    action();
    this._emit();
    this._render();
  }

  _render() {
    const parent = this._container();
    const settings = this.selector?.grenton_thermostat ?? {};
    this._value ??= { cooling_enabled: false, edit_schedule: false, sections: [] };
    const draft = this._value;
    draft.schedule_polling_enabled ??= true;
    this._periodTemperatureInputs = [];
    const cooling = this._input("cooling_enabled", draft.cooling_enabled,
      (value) => { draft.cooling_enabled = value; this._render(); }, "checkbox", false);
    cooling.disabled ||= !settings.cooling_available;
    parent.append(this._field(this._label("cooling_enabled", "Enable cooling"), cooling));
    if (draft.cooling_enabled && settings.cooling_available) {
      parent.append(this._field(this._label("control_direction", "Control direction (preserves manual/schedule mode)"),
        this._select("control_direction", [
          { value: "unchanged", label: this._label("unchanged", "Keep current direction") },
          { value: "heating", label: this._label("heating", "Heating") },
          { value: "cooling", label: this._label("cooling", "Cooling") },
        ], draft.control_direction ?? "unchanged", (value) => { draft.control_direction = value; })));
      if (settings.direction) {
        const current = document.createElement("p");
        current.className = "hint";
        current.textContent = `${this._label("current_direction", "Current direction")}: ${this._label(settings.direction, settings.direction)}`;
        parent.append(current);
      }
    }
    const limits = this._input("edit_limits", draft.edit_limits ?? false,
      (value) => { draft.edit_limits = value; this._render(); }, "checkbox", false);
    limits.disabled ||= !settings.limits_available;
    parent.append(this._field(this._label("edit_limits", "Edit temperature limits"), limits));
    if (draft.edit_limits && settings.limits_available) {
      for (const name of ["minimum", "maximum"]) {
        draft[name] ??= settings[name];
        const input = this._input(name, draft[name],
          (value) => {
            draft[name] = value;
            for (const period of this._periodTemperatureInputs) {
              period[name === "minimum" ? "min" : "max"] = String(value);
            }
          }, "number");
        input.step = "0.5";
        input.min = "0";
        parent.append(this._field(this._label(name, name === "minimum" ? "Minimum temperature (°C)" : "Maximum temperature (°C)"), input));
      }
      const note = document.createElement("p");
      note.className = "hint";
      note.textContent = this._label("limits_hint", "Scheduled temperatures are preserved when the range changes. All targets must fit the new limits; edit the schedule below if needed.");
      parent.append(note);
    }
    const sync = this._input("schedule_polling_enabled", draft.schedule_polling_enabled,
      (value) => { draft.schedule_polling_enabled = value; }, "checkbox", false);
    parent.append(this._field(this._label("schedule_polling_enabled", "Automatically sync schedule"), sync));
    const edit = this._input("edit_schedule", draft.edit_schedule,
      (value) => { draft.edit_schedule = value; this._render(); }, "checkbox", false);
    edit.disabled ||= !settings.schedule_available;
    parent.append(this._field(this._label("edit_schedule", "Edit weekly schedule"), edit));
    const hint = document.createElement("p");
    hint.className = "hint";
    hint.textContent = settings.schedule_available
      ? this._label("schedule_hint", "Assign each day to one section. Each period lasts until the next start time; the last ends at midnight. Temperatures are in °C. Auto preserves the current heating/cooling direction.")
      : this._label("schedule_unavailable", "Wait for the current schedule and temperature limits from the CLU, then reopen configuration.");
    parent.append(hint);
    if (!settings.cooling_available) {
      const unavailable = document.createElement("p");
      unavailable.className = "hint";
      unavailable.textContent = this._label("cooling_unavailable", "Cooling requires readable and writable thermostat direction bindings.");
      parent.append(unavailable);
    }
    if (!draft.edit_schedule || !settings.schedule_available) return;
    const sections = draft.sections ??= [];
    const bounds = draft.edit_limits && settings.limits_available
      ? { ...settings, minimum: draft.minimum, maximum: draft.maximum } : settings;
    sections.forEach((section, index) => this._renderSection(parent, section, index, bounds));
    parent.append(this._button(this._label("add_section", "Add section"), () => this._change(() => {
      const assigned = new Set(sections.flatMap((section) => section.days));
      sections.push({ days: WEEKDAYS.filter((day) => !assigned.has(day)), periods: [{
        time: "00:00", temperature: sections[0]?.periods[0]?.temperature ?? Math.max(0, settings.minimum ?? 0),
      }] });
    }), sections.length >= 7));
  }

  _periodTime(name, period, fixed, onChange) {
    const group = document.createElement("fieldset");
    group.className = "schedule-time";
    group.setAttribute("aria-label", this._label("start_time", "Start time"));
    const [initialHour, initialMinute] = period.time.split(":");
    const update = () => {
      const rawHour = hour.value;
      // Keep the input itself untouched while typing. Emit invalid drafts too,
      // so Save cannot silently submit the previous valid time.
      const valid = /^(?:[01]?\d|2[0-3])$/.test(rawHour);
      period.time = `${valid ? rawHour.padStart(2, "0") : rawHour}:${minute.value}`;
      onChange();
    };
    const hour = this._input(`${name}_hour`, initialHour, update);
    hour.setAttribute("aria-label", this._label("hour", "Hour"));
    hour.inputMode = "numeric";
    hour.maxLength = 2;
    hour.pattern = "(?:[01]?[0-9]|2[0-3])";
    hour.disabled ||= fixed;
    hour.addEventListener("focus", () => hour.select());
    hour.addEventListener("blur", () => {
      if (/^(?:[01]?\d|2[0-3])$/.test(hour.value)) {
        hour.value = hour.value.padStart(2, "0");
      }
    });
    const minute = this._select(`${name}_minute`,
      ["00", "15", "30", "45"].map((value) => ({ value, label: value })),
      initialMinute, update);
    minute.disabled ||= fixed;
    minute.setAttribute("aria-label", this._label("minute", "Minute"));
    const separator = document.createElement("span");
    separator.textContent = ":";
    separator.setAttribute("aria-hidden", "true");
    group.append(hour, separator, minute);
    return group;
  }

  _renderSection(parent, section, index, settings) {
    const container = document.createElement("div");
    container.className = "argument";
    container.dataset.section = index;
    const heading = document.createElement("div");
    heading.className = "heading";
    const title = document.createElement("strong");
    title.textContent = `${this._label("section", "Section")} ${index + 1}`;
    heading.append(title, this._button(this._label("remove_section", "Remove section"), () => this._change(() => {
      this._value.sections.splice(index, 1);
    }), this._value.sections.length === 1));
    container.append(heading);
    const presets = { weekdays: WEEKDAYS.slice(0, 5), weekend: WEEKDAYS.slice(5), all: WEEKDAYS };
    const preset = Object.keys(presets).find((key) =>
      presets[key].length === section.days.length && presets[key].every((day) => section.days.includes(day))) ?? "custom";
    container.append(this._field(this._label("days", "Days"), this._select(`section_${index}_days`, [
      { value: "weekdays", label: this._label("weekdays", "Monday–Friday") },
      { value: "weekend", label: this._label("weekend", "Saturday–Sunday") },
      { value: "all", label: this._label("all", "Every day") },
      { value: "custom", label: this._label("custom", "Selected days") },
    ], preset, (value) => {
      if (presets[value]) section.days = [...presets[value]];
      this._render();
    })));
    const days = document.createElement("div");
    days.className = "inputs";
    WEEKDAYS.forEach((day) => {
      days.append(this._field(this._label(day, day), this._input(`section_${index}_${day}`, section.days.includes(day),
        (checked) => {
          section.days = checked ? [...section.days, day] : section.days.filter((item) => item !== day);
          this._render();
        }, "checkbox", false)));
    });
    container.append(days);
    const used = this._value.sections.flatMap((item) => item.days);
    if (section.days.length === 0 || section.days.some((day) => used.filter((item) => item === day).length > 1)) {
      const warning = document.createElement("p");
      warning.className = "hint";
      warning.textContent = this._label("day_conflict", "Select at least one day per section, with no day shared between sections.");
      container.append(warning);
    }
    const periods = section.periods;
    const nextSlot = () => {
      const slots = periods.map((period) => {
        const match = /^([01]\d|2[0-3]):(00|15|30|45)$/.exec(period.time);
        return match ? Number(match[1]) * 4 + Number(match[2]) / 15 : NaN;
      });
      return slots.every(Number.isFinite) ? Math.max(...slots) + 1 : 96;
    };
    let addPeriod;
    const updateAddPeriod = () => {
      addPeriod.disabled = this.disabled || periods.length >= 96 || nextSlot() >= 96;
    };
    const rows = document.createElement("div");
    rows.className = "schedule-periods";
    const headings = document.createElement("div");
    headings.className = "schedule-period-row schedule-period-headings";
    for (const [name, fallback] of [["start_time", "Start time"], ["temperature", "Temperature (°C)"]]) {
      const title = document.createElement("span");
      title.textContent = this._label(name, fallback);
      headings.append(title);
    }
    rows.append(headings);
    periods.forEach((period, periodIndex) => {
      const row = document.createElement("div");
      row.className = "schedule-period-row";
      const time = this._periodTime(`section_${index}_period_${periodIndex}_time`,
        period, periodIndex === 0, updateAddPeriod);
      const temperature = this._input(`section_${index}_period_${periodIndex}_temperature`, period.temperature,
        (value) => { period.temperature = value; }, "number");
      this._periodTemperatureInputs.push(temperature);
      temperature.step = "0.5";
      temperature.min = String(Math.max(0, settings.minimum ?? 0));
      temperature.max = String(settings.maximum);
      temperature.setAttribute("aria-label", this._label("temperature", "Temperature (°C)"));
      const remove = this._button("×", () => this._change(() => {
        periods.splice(periodIndex, 1);
      }), periodIndex === 0, this._label("remove_period", "Remove period"));
      remove.className = "schedule-period-remove";
      row.append(time, temperature, remove);
      rows.append(row);
    });
    container.append(rows);
    addPeriod = this._button(this._label("add_period", "Add period"), () => this._change(() => {
      const slot = nextSlot();
      periods.sort((a, b) => a.time.localeCompare(b.time));
      const time = `${String(Math.floor(slot / 4)).padStart(2, "0")}:${String(slot % 4 * 15).padStart(2, "0")}`;
      periods.push({ time, temperature: periods.at(-1).temperature });
    }));
    updateAddPeriod();
    container.append(addPeriod);
    parent.append(container);
  }
}

if (!customElements.get("ha-selector-grenton_thermostat")) {
  customElements.define("ha-selector-grenton_thermostat", GrentonThermostatEditor);
}

// ---------------------------------------------------------------------------
// Thermostat schedule dashboard card (scoped block: no clash with the selectors above)
{
// Grenton thermostat card with a weekly schedule editor.
//
// Tile per thermostat (status, current temperature, setpoint -/+, Off/Heat/Auto,
// "Schedule" button). The schedule opens in a dialog: a week grid of coloured
// temperature blocks and an editor for the selected day. Saving uses
// grenton.set_thermostat_schedule.
//
//   type: custom:grenton-schedule-card
//   entities:            # optional; default: every Grenton thermostat
//     - climate.ogrzewanie_ania
//   title: Ogrzewanie    # optional

const DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"];
const TEXT = {
  pl: {
    days: ["Pon", "Wt", "Śr", "Czw", "Pt", "Sob", "Nd"],
    dayNames: ["Poniedziałek", "Wtorek", "Środa", "Czwartek", "Piątek", "Sobota", "Niedziela"],
    setpoint: "Nastawa", schedule: "Harmonogram", off: "Wył.", heat: "Grzanie", cool: "Chłodzenie", auto: "Auto",
    heating: "Grzeje", cooling: "Chłodzi", idle: "Bezczynny", offState: "Wyłączony",
    copy: "Kopiuj na:", weekdays: "dni robocze", weekend: "weekend", week: "cały tydzień",
    add: "Dodaj zmianę temperatury", remove: "Usuń", save: "Zapisz", cancel: "Anuluj", saving: "Zapisywanie…",
    title: (name) => `${name} – harmonogram`,
    notAuto: "Termostat nie jest w trybie Auto – harmonogram zacznie działać po włączeniu Auto.",
    setAuto: "Włącz Auto",
    noSchedule: "Harmonogram nie został jeszcze odczytany z CLU.",
    none: "Brak termostatów Grenton.",
    copied: "Skopiowano",
    range: (min, max) => `Temperatura musi być w zakresie ${min}–${max} °C.`,
  },
  en: {
    days: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    dayNames: ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
    setpoint: "Setpoint", schedule: "Schedule", off: "Off", heat: "Heat", cool: "Cool", auto: "Auto",
    heating: "Heating", cooling: "Cooling", idle: "Idle", offState: "Off",
    copy: "Copy to:", weekdays: "weekdays", weekend: "weekend", week: "whole week",
    add: "Add temperature change", remove: "Remove", save: "Save", cancel: "Cancel", saving: "Saving…",
    title: (name) => `${name} – schedule`,
    notAuto: "The thermostat is not in Auto – the schedule applies once Auto is on.",
    setAuto: "Switch to Auto",
    noSchedule: "The schedule has not been read from the CLU yet.",
    none: "No Grenton thermostats.",
    copied: "Copied",
    range: (min, max) => `Temperature must be within ${min}–${max} °C.`,
  },
};

const STYLE = `
  :host { display: block; }
  * { box-sizing: border-box; }
  .tiles { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 12px; }
  .heading { font-size: 18px; font-weight: 500; margin: 4px 4px 12px; color: var(--primary-text-color); }
  ha-card.tile { padding: 14px; color: var(--primary-text-color); display: flex; flex-direction: column; gap: 10px; }
  .top { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
  .name { font-weight: 600; font-size: 15px; display: flex; align-items: center; gap: 6px; min-width: 0; }
  .name span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .chip { font-size: 12px; font-weight: 600; padding: 3px 10px; border-radius: 10px; white-space: nowrap;
          background: var(--secondary-background-color); color: var(--secondary-text-color); }
  .chip.heating { background: rgba(255, 152, 0, .22); color: var(--state-climate-heat-color, #e8860f); }
  .chip.cooling { background: rgba(33, 150, 243, .2); color: var(--state-climate-cool-color, #2196f3); }
  .current { font-size: 44px; font-weight: 600; line-height: 1.1; margin: 8px 0 4px; }
  .setpoint { display: grid; grid-template-columns: 48px 1fr 48px; align-items: center; text-align: center; }
  .setpoint small { display: block; font-size: 12px; color: var(--secondary-text-color); }
  .setpoint b { font-size: 24px; }
  .round { width: 44px; height: 44px; border-radius: 50%; border: none; cursor: pointer; font-size: 22px;
           background: var(--secondary-background-color); color: var(--primary-text-color); }
  .round:disabled { opacity: .4; cursor: default; }
  .modes { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; }
  .mode, .wide { border: none; border-radius: 10px; padding: 10px 6px; cursor: pointer; font: inherit; font-size: 13px; font-weight: 600;
                 background: var(--secondary-background-color); color: var(--primary-text-color); }
  .mode.active { background: rgba(255, 152, 0, .3); color: var(--state-climate-heat-color, #e8860f); }
  .mode.active.auto { background: rgba(76, 175, 80, .25); color: var(--state-climate-auto-color, #4caf50); }
  .mode.active.off { background: rgba(127, 127, 127, .35); color: var(--primary-text-color); }
  .backdrop { position: fixed; inset: 0; background: rgba(0, 0, 0, .45); z-index: 9; display: flex;
              align-items: center; justify-content: center; padding: 12px; }
  .dialog { background: var(--card-background-color, #fff); color: var(--primary-text-color); border-radius: 20px;
            width: min(760px, 100%); max-height: 92vh; overflow: auto; padding: 16px 16px 12px;
            box-shadow: 0 10px 40px rgba(0, 0, 0, .35); }
  .dialog-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
  .dialog-head h3 { margin: 0; font-size: 17px; }
  .close { width: 40px; height: 40px; border-radius: 12px; border: 1px solid var(--divider-color); background: none;
           color: var(--primary-text-color); cursor: pointer; font-size: 20px; }
  .week { display: grid; grid-template-columns: 44px 1fr; gap: 6px 8px; align-items: center; }
  .week .day { font-size: 13px; font-weight: 600; padding: 6px 4px; border-radius: 8px; cursor: pointer; }
  .week .row { display: flex; height: 28px; border-radius: 8px; overflow: hidden; cursor: pointer; outline-offset: 2px; }
  .week .row.selected { outline: 2px solid var(--primary-color); }
  .week .day.selected { background: var(--secondary-background-color); }
  .seg { display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 700;
         color: rgba(0, 0, 0, .75); overflow: hidden; white-space: nowrap; border-right: 1px solid rgba(255,255,255,.5); }
  .axis { grid-column: 2; display: flex; justify-content: space-between; font-size: 11px; color: var(--secondary-text-color); }
  .editor { margin-top: 14px; background: var(--secondary-background-color); border-radius: 14px; padding: 12px; }
  .editor-head { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 8px; }
  .editor-head h4 { margin: 0; font-size: 16px; }
  .copy { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; font-size: 13px; color: var(--secondary-text-color); }
  .pill { border: 1px solid var(--divider-color); background: var(--card-background-color); color: var(--primary-text-color);
          border-radius: 14px; padding: 4px 10px; cursor: pointer; font: inherit; font-size: 12px; font-weight: 600; }
  .period { display: grid; grid-template-columns: 8px 92px 1fr 40px 56px 40px 32px; gap: 8px; align-items: center; padding: 5px 0; }
  .swatch { width: 8px; height: 28px; border-radius: 4px; }
  .period select { font: inherit; font-weight: 700; padding: 6px; border-radius: 8px; border: 1px solid var(--divider-color);
                   background: var(--card-background-color); color: var(--primary-text-color); width: 100%; }
  .period .fixed { font-weight: 700; padding-left: 8px; }
  .until { font-size: 13px; color: var(--secondary-text-color); white-space: nowrap; }
  .temp { text-align: center; font-size: 20px; font-weight: 700; }
  .period .round { width: 40px; height: 40px; font-size: 20px; background: var(--card-background-color); }
  .x { border: none; background: none; color: var(--secondary-text-color); cursor: pointer; font-size: 18px; }
  .x:disabled { visibility: hidden; }
  .add { margin-top: 6px; border: 1px dashed var(--divider-color); background: none; color: var(--primary-text-color);
         border-radius: 10px; padding: 8px 14px; cursor: pointer; font: inherit; font-weight: 600; }
  .add:disabled { opacity: .4; cursor: default; }
  .warn { font-size: 13px; padding: 8px 12px; border-radius: 10px; margin-bottom: 12px; display: flex;
          gap: 8px; align-items: center; justify-content: space-between; background: rgba(255, 152, 0, .15); }
  .footer { display: flex; justify-content: flex-end; gap: 8px; margin-top: 12px; align-items: center; }
  .error { color: var(--error-color, #db4437); font-size: 13px; margin-right: auto; }
  .btn { border: 1px solid var(--divider-color); background: none; color: var(--primary-text-color); border-radius: 10px;
         padding: 9px 16px; cursor: pointer; font: inherit; font-weight: 600; }
  .btn.primary { background: var(--primary-color); border-color: var(--primary-color); color: var(--text-primary-color, #fff); }
  .btn:disabled { opacity: .5; cursor: default; }
  .muted { color: var(--secondary-text-color); font-size: 14px; }
  @media (max-width: 520px) {
    .period { grid-template-columns: 8px 84px 1fr 36px 48px 36px 24px; gap: 6px; }
    .until { font-size: 11px; }
  }
`;

const clone = (value) => JSON.parse(JSON.stringify(value));
const minutes = (time) => { const [h, m] = time.split(":").map(Number); return h * 60 + m; };
const hhmm = (total) => `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
const fmt = (value, lang, decimals) => {
  const text = Number(value).toFixed(decimals ?? (Number(value) % 1 ? 1 : 0));
  return lang === "pl" ? text.replace(".", ",") : text;
};

// Cool (blue) -> comfortable (green/yellow) -> warm (orange/red), fixed scale so
// the same temperature always has the same colour.
function colour(temperature) {
  const stops = [[16, [126, 178, 221]], [19, [126, 178, 221]], [20.5, [205, 226, 90]],
                 [21.5, [230, 196, 80]], [22.5, [232, 139, 76]], [25, [220, 90, 70]]];
  const t = Number(temperature);
  if (t <= stops[0][0]) return `rgb(${stops[0][1]})`;
  for (let i = 1; i < stops.length; i += 1) {
    const [t1, c1] = stops[i];
    const [t0, c0] = stops[i - 1];
    if (t <= t1) {
      const k = (t - t0) / (t1 - t0);
      return `rgb(${c0.map((v, j) => Math.round(v + (c1[j] - v) * k)).join(",")})`;
    }
  }
  return `rgb(${stops[stops.length - 1][1]})`;
}

class GrentonScheduleCard extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
    this._dialog = null; // {id, week, day, saving, error, dirty}
    if (this._hass) this._renderAll();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first || !this.shadowRoot) this._renderAll();
    else this._renderTiles();
    if (this._dialog && !this._dialog.dirty && !this._dialog.saving) {
      // Follow CLU changes while the user has not edited anything
      const week = hass.states[this._dialog.id]?.attributes.weekly_schedule;
      if (week && JSON.stringify(week) !== JSON.stringify(this._dialog.base)) {
        this._dialog.week = clone(week);
        this._dialog.base = clone(week);
        this._renderDialog();
      }
    }
  }

  getCardSize() { return 6; }
  static getStubConfig() { return {}; }

  get _t() { return TEXT[this._lang]; }
  get _lang() { return (this._hass?.language || "en").startsWith("pl") ? "pl" : "en"; }

  _entities() {
    const hass = this._hass;
    const configured = this._config.entities || (this._config.entity ? [this._config.entity] : null);
    const ids = configured || Object.keys(hass.states).filter((id) =>
      id.startsWith("climate.")
      && hass.entities?.[id]?.platform === "grenton"
      && "schedule_status" in hass.states[id].attributes);
    return ids.filter((id) => hass.states[id]).sort((a, b) => this._name(a).localeCompare(this._name(b)));
  }

  _name(id) { return this._hass.states[id]?.attributes.friendly_name || id; }

  _renderAll() {
    if (!this._hass || !this._config) return;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `<style>${STYLE}</style><div class="wrap"></div><div class="dialog-root"></div>`;
    this._renderTiles();
    this._renderDialog();
  }

  // ---------------------------------------------------------------- tiles
  _renderTiles() {
    const t = this._t;
    const wrap = this.shadowRoot.querySelector(".wrap");
    wrap.innerHTML = "";
    if (this._config.title) {
      wrap.appendChild(Object.assign(document.createElement("div"), { className: "heading", textContent: this._config.title }));
    }
    const entities = this._entities();
    if (!entities.length) {
      const card = document.createElement("ha-card");
      card.className = "tile";
      card.appendChild(Object.assign(document.createElement("div"), { className: "muted", textContent: t.none }));
      wrap.appendChild(card);
      return;
    }
    const tiles = document.createElement("div");
    tiles.className = "tiles";
    for (const id of entities) tiles.appendChild(this._tile(id));
    wrap.appendChild(tiles);
  }

  _tile(id) {
    const t = this._t;
    const lang = this._lang;
    const state = this._hass.states[id];
    const a = state.attributes;
    const card = document.createElement("ha-card");
    card.className = "tile";

    const action = a.hvac_action;
    const chipClass = action === "heating" ? "heating" : action === "cooling" ? "cooling" : "";
    const chipText = state.state === "off" ? t.offState
      : action === "heating" ? t.heating : action === "cooling" ? t.cooling : t.idle;
    card.innerHTML = `
      <div class="top"><div class="name">🔥<span></span></div><div class="chip ${chipClass}"></div></div>
      <div class="current"></div>
      <div class="setpoint"><button class="round minus">−</button><div><small>${t.setpoint}</small><b></b></div><button class="round plus">+</button></div>
      <div class="modes"></div>
      <button class="wide">🗓 ${t.schedule}</button>`;
    card.querySelector(".name span").textContent = this._name(id);
    card.querySelector(".chip").textContent = chipText;
    card.querySelector(".current").textContent =
      a.current_temperature != null ? `${fmt(a.current_temperature, lang, 1)}°` : "–";
    const target = a.temperature;
    card.querySelector(".setpoint b").textContent = target != null ? `${fmt(target, lang, 1)}°` : "–";

    const step = Number(a.target_temp_step || 0.5);
    const change = (delta) => {
      const next = Math.min(Number(a.max_temp ?? 35), Math.max(Number(a.min_temp ?? 5), Number(target) + delta));
      this._hass.callService("climate", "set_temperature", { entity_id: id, temperature: next });
    };
    const minus = card.querySelector(".minus");
    const plus = card.querySelector(".plus");
    minus.disabled = plus.disabled = target == null || state.state === "off";
    minus.onclick = () => change(-step);
    plus.onclick = () => change(step);

    const modes = card.querySelector(".modes");
    const available = a.hvac_modes || ["off", "heat", "auto"];
    for (const [mode, label] of [["off", t.off], ["heat", t.heat], ["cool", t.cool], ["auto", t.auto]]) {
      if (!available.includes(mode)) continue;
      const button = document.createElement("button");
      button.className = `mode ${mode}${state.state === mode ? " active" : ""}`;
      button.textContent = label;
      button.onclick = () => this._hass.callService("climate", "set_hvac_mode", { entity_id: id, hvac_mode: mode });
      modes.appendChild(button);
    }
    modes.style.gridTemplateColumns = `repeat(${modes.children.length}, 1fr)`;
    card.querySelector(".wide").onclick = () => this._open(id);
    return card;
  }

  // ---------------------------------------------------------------- dialog
  _open(id) {
    const week = this._hass.states[id]?.attributes.weekly_schedule;
    const today = (new Date().getDay() + 6) % 7;
    this._dialog = { id, week: week ? clone(week) : null, base: week ? clone(week) : null, day: today, dirty: false };
    this._renderDialog();
  }

  _close() {
    this._dialog = null;
    this._renderDialog();
  }

  _bounds() {
    const a = this._hass.states[this._dialog.id].attributes;
    return { min: Number(a.min_temp ?? 5), max: Number(a.max_temp ?? 35), step: Number(a.target_temp_step || 0.5) };
  }

  _edit(mutate) {
    mutate(this._dialog.week);
    for (const day of DAYS) this._dialog.week[day].sort((p, q) => minutes(p.time) - minutes(q.time));
    this._dialog.dirty = true;
    this._dialog.error = null;
    this._renderDialog();
  }

  _renderDialog() {
    const root = this.shadowRoot?.querySelector(".dialog-root");
    if (!root) return;
    root.innerHTML = "";
    const d = this._dialog;
    if (!d) return;
    const t = this._t;
    const lang = this._lang;
    const state = this._hass.states[d.id];

    const backdrop = document.createElement("div");
    backdrop.className = "backdrop";
    backdrop.onclick = (event) => { if (event.target === backdrop && !d.dirty) this._close(); };
    const dialog = document.createElement("div");
    dialog.className = "dialog";
    backdrop.appendChild(dialog);

    const head = document.createElement("div");
    head.className = "dialog-head";
    head.innerHTML = `<h3>🗓 <span></span></h3><button class="close" title="${t.cancel}">✕</button>`;
    head.querySelector("span").textContent = t.title(this._name(d.id));
    head.querySelector(".close").onclick = () => this._close();
    dialog.appendChild(head);

    if (state && state.state !== "auto" && state.state !== "off") {
      const warn = document.createElement("div");
      warn.className = "warn";
      warn.innerHTML = `<span>${t.notAuto}</span>`;
      const auto = Object.assign(document.createElement("button"), { className: "pill", textContent: t.setAuto });
      auto.onclick = () => this._hass.callService("climate", "set_hvac_mode", { entity_id: d.id, hvac_mode: "auto" });
      warn.appendChild(auto);
      dialog.appendChild(warn);
    }

    if (!d.week) {
      dialog.appendChild(Object.assign(document.createElement("div"), {
        className: "muted", textContent: `${t.noSchedule} ${state?.attributes.schedule_status || ""}`,
      }));
      root.appendChild(backdrop);
      return;
    }

    // Week overview
    const week = document.createElement("div");
    week.className = "week";
    DAYS.forEach((day, index) => {
      const label = Object.assign(document.createElement("div"), {
        className: `day${index === d.day ? " selected" : ""}`, textContent: t.days[index],
      });
      const row = document.createElement("div");
      row.className = `row${index === d.day ? " selected" : ""}`;
      const periods = d.week[day];
      periods.forEach((period, i) => {
        const start = minutes(period.time);
        const end = i + 1 < periods.length ? minutes(periods[i + 1].time) : 1440;
        const seg = document.createElement("div");
        seg.className = "seg";
        seg.style.flex = String(end - start);
        seg.style.background = colour(period.temperature);
        seg.textContent = end - start >= 90 ? `${fmt(period.temperature, lang)}°` : "";
        seg.title = `${period.time}–${hhmm(end)}: ${fmt(period.temperature, lang)} °C`;
        row.appendChild(seg);
      });
      const select = () => { d.day = index; this._renderDialog(); };
      label.onclick = select;
      row.onclick = select;
      week.append(label, row);
    });
    const axis = document.createElement("div");
    axis.className = "axis";
    axis.innerHTML = "<span>0</span><span>6</span><span>12</span><span>18</span><span>24</span>";
    week.append(document.createElement("div"), axis);
    dialog.appendChild(week);

    // Day editor
    const { min, max, step } = this._bounds();
    const day = DAYS[d.day];
    const periods = d.week[day];
    const editor = document.createElement("div");
    editor.className = "editor";
    const editorHead = document.createElement("div");
    editorHead.className = "editor-head";
    editorHead.innerHTML = `<h4>${t.dayNames[d.day]}</h4><div class="copy">${t.copy}</div>`;
    const copy = editorHead.querySelector(".copy");
    for (const [label, targets] of [[t.weekdays, DAYS.slice(0, 5)], [t.weekend, DAYS.slice(5)], [t.week, DAYS]]) {
      const pill = Object.assign(document.createElement("button"), { className: "pill", textContent: label });
      pill.onclick = () => this._edit((w) => { for (const target of targets) w[target] = clone(w[day]); });
      copy.appendChild(pill);
    }
    editor.appendChild(editorHead);

    periods.forEach((period, index) => {
      const start = minutes(period.time);
      const prev = index > 0 ? minutes(periods[index - 1].time) : 0;
      const next = index + 1 < periods.length ? minutes(periods[index + 1].time) : 1440;
      const row = document.createElement("div");
      row.className = "period";
      const swatch = document.createElement("div");
      swatch.className = "swatch";
      swatch.style.background = colour(period.temperature);

      let time;
      if (index === 0) {
        time = Object.assign(document.createElement("div"), { className: "fixed", textContent: "00:00" });
      } else {
        time = document.createElement("select");
        for (let m = prev + 15; m < next; m += 15) time.add(new Option(hhmm(m), hhmm(m)));
        time.value = period.time;
        time.onchange = () => this._edit((w) => { w[day][index].time = time.value; });
      }
      const until = Object.assign(document.createElement("div"), { className: "until", textContent: `– ${next === 1440 ? "24:00" : hhmm(next)}` });
      const minus = Object.assign(document.createElement("button"), { className: "round", textContent: "−" });
      const temp = Object.assign(document.createElement("div"), { className: "temp", textContent: `${fmt(period.temperature, lang)}°` });
      const plus = Object.assign(document.createElement("button"), { className: "round", textContent: "+" });
      minus.disabled = Number(period.temperature) - step < min - 1e-9;
      plus.disabled = Number(period.temperature) + step > max + 1e-9;
      minus.onclick = () => this._edit((w) => { w[day][index].temperature = Number(period.temperature) - step; });
      plus.onclick = () => this._edit((w) => { w[day][index].temperature = Number(period.temperature) + step; });
      const remove = Object.assign(document.createElement("button"), { className: "x", textContent: "✕", title: t.remove });
      remove.disabled = index === 0;
      remove.onclick = () => this._edit((w) => { w[day].splice(index, 1); });
      row.append(swatch, time, until, minus, temp, plus, remove);
      editor.appendChild(row);
    });

    // New change: middle of the longest period, on a quarter hour
    let best = null;
    periods.forEach((period, index) => {
      const start = minutes(period.time);
      const end = index + 1 < periods.length ? minutes(periods[index + 1].time) : 1440;
      if (end - start >= 30 && (!best || end - start > best.length)) best = { start, length: end - start, temperature: period.temperature };
    });
    const add = Object.assign(document.createElement("button"), { className: "add", textContent: `+ ${t.add}` });
    add.disabled = !best;
    add.onclick = () => this._edit((w) => {
      const at = best.start + Math.max(15, Math.round(best.length / 2 / 15) * 15);
      w[day].push({ time: hhmm(at), temperature: best.temperature });
    });
    editor.appendChild(add);
    dialog.appendChild(editor);

    const footer = document.createElement("div");
    footer.className = "footer";
    if (d.error) footer.appendChild(Object.assign(document.createElement("div"), { className: "error", textContent: d.error }));
    const cancel = Object.assign(document.createElement("button"), { className: "btn", textContent: t.cancel });
    cancel.onclick = () => this._close();
    const save = Object.assign(document.createElement("button"), { className: "btn primary", textContent: d.saving ? t.saving : t.save });
    save.disabled = !d.dirty || d.saving;
    save.onclick = () => this._save();
    footer.append(cancel, save);
    dialog.appendChild(footer);
    root.appendChild(backdrop);
  }

  async _save() {
    const d = this._dialog;
    const { min, max } = this._bounds();
    for (const day of DAYS) {
      for (const period of d.week[day]) {
        if (period.temperature < min || period.temperature > max) {
          d.error = this._t.range(min, max);
          this._renderDialog();
          return;
        }
      }
    }
    d.saving = true;
    d.error = null;
    this._renderDialog();
    try {
      const schedule = Object.fromEntries(DAYS.map((day) => [day,
        d.week[day].map((p) => ({ time: p.time, temperature: Number(p.temperature) }))]));
      await this._hass.callService("grenton", "set_thermostat_schedule", { schedule }, { entity_id: d.id });
      this._close();
    } catch (err) {
      d.saving = false;
      d.error = err?.message || String(err);
      this._renderDialog();
    }
  }
}

if (!customElements.get("grenton-schedule-card")) {
  customElements.define("grenton-schedule-card", GrentonScheduleCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "grenton-schedule-card",
    name: "Grenton – thermostat & schedule",
    description: "Grenton thermostats with setpoint, mode and a weekly schedule editor.",
    preview: false,
  });
}

}
