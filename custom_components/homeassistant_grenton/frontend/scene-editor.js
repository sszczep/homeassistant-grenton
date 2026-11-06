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
