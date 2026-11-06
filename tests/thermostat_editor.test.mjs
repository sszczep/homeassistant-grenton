// Exercise the real popup renderer and events without a Home Assistant server.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const component = new URL("../custom_components/homeassistant_grenton/", import.meta.url);
const source = readFileSync(new URL("frontend/scene-editor.js", component), "utf8");
const DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"];

class Element {
  constructor(tag) {
    this.tag = tag; this.children = []; this.dataset = {}; this.listeners = {};
    this.isConnected = true;
  }
  append(...children) { this.children.push(...children); }
  setAttribute(name, value) { (this.attributes ??= {})[name] = value; }
  select() { this.selectionStart = 0; this.selectionEnd = this.value.length; }
  addEventListener(event, listener) { this.listeners[event] = listener; }
  fire(event) { if (!this.disabled) this.listeners[event]?.(); }
}
const descendants = (element) => [element, ...element.children.flatMap(descendants)];

function makeEditor({ language = "en", settings = {}, sections, edit = true, schedulePolling } = {}) {
  const elements = new Map();
  vm.runInNewContext(source, {
    HTMLElement: class {}, structuredClone,
    document: { createElement: (tag) => new Element(tag) },
    CustomEvent: class { constructor(type, options) { this.type = type; Object.assign(this, options); } },
    customElements: { get: (name) => elements.get(name), define: (name, cls) => elements.set(name, cls) },
  });
  const editor = Object.create(elements.get("ha-selector-grenton_thermostat").prototype);
  editor._value = { cooling_enabled: false, edit_schedule: edit, sections: structuredClone(sections ?? [{
    days: DAYS, periods: [{ time: "00:00", temperature: 20 }],
  }]) };
  if (schedulePolling !== undefined) editor._value.schedule_polling_enabled = schedulePolling;
  editor._selector = { grenton_thermostat: { cooling_available: true, schedule_available: true, minimum: 10, maximum: 30, ...settings } };
  const translations = JSON.parse(readFileSync(new URL(`translations/${language}.json`, component), "utf8")).selector;
  editor._localizeValue = (key) => key.split(".").reduce((value, part) => value?.[part], translations);
  editor._container = () => (editor.root = new Element("div"));
  editor.dispatchEvent = (event) => { editor.emitted = structuredClone(event.detail.value); };
  editor.field = (name) => descendants(editor.root).find((item) => item.dataset.field === name);
  editor.section = (index) => descendants(editor.root).find((item) => item.dataset.section === index);
  editor.button = (text, root = editor.root) => descendants(root).find((item) => item.tag === "button" && item.textContent === text);
  editor._render();
  return editor;
}

for (const language of ["en", "pl"]) {
  test(`${language}: thermostat popup localizes controls and keeps schedule opt-in`, () => {
    const editor = makeEditor({ language, edit: false });
    assert.equal(editor.section(0), undefined);
    assert.equal(editor.field("cooling_enabled").checked, false);
    assert.match(descendants(editor.root).map((item) => item.textContent ?? "").join(" "),
      language === "pl" ? /Włącz chłodzenie/ : /Enable cooling/);
    editor.field("edit_schedule").checked = true;
    editor.field("edit_schedule").fire("input");
    assert.ok(editor.section(0));
    assert.equal(editor.field("section_0_period_0_temperature").step, "0.5");
    assert.equal(editor.field("section_0_period_0_temperature").min, "10");
    assert.equal(editor.field("section_0_period_0_temperature").max, "30");
    assert.equal(editor.field("section_0_period_0_time_hour").disabled, true);
    assert.equal(editor.field("section_0_period_0_time_minute").disabled, true);
  });
  test(`${language}: schedule sync is enabled by default and can be disabled without schedule data`, () => {
    const editor = makeEditor({ language, edit: false, settings: { schedule_available: false } });
    const sync = editor.field("schedule_polling_enabled");
    assert.equal(sync.checked, true);
    assert.ok(!sync.disabled);
    assert.match(descendants(editor.root).map((item) => item.textContent ?? "").join(" "),
      language === "pl" ? /Automatyczna synchronizacja harmonogramu/ : /Automatically sync schedule/);
    const sections = structuredClone(editor.value.sections);
    sync.checked = false;
    sync.fire("input");
    assert.equal(editor.emitted.schedule_polling_enabled, false);
    assert.deepEqual(editor.emitted.sections, sections);
    assert.equal(editor.emitted.edit_schedule, false);
    editor._render();
    assert.equal(editor.field("schedule_polling_enabled").checked, false);
    const restored = makeEditor({ language, schedulePolling: false });
    assert.equal(restored.field("schedule_polling_enabled").checked, false);
    restored.field("schedule_polling_enabled").checked = true;
    restored.field("schedule_polling_enabled").fire("input");
    assert.equal(restored.emitted.schedule_polling_enabled, true);
  });
}

test("the schedule sync option respects a disabled thermostat editor", () => {
  const editor = makeEditor();
  editor._disabled = true;
  editor._render();
  assert.equal(editor.field("schedule_polling_enabled").disabled, true);
});

test("day sections support presets, individual weekdays and removal", () => {
  const editor = makeEditor();
  editor.field("section_0_days").value = "weekdays";
  editor.field("section_0_days").fire("change");
  assert.deepEqual(editor.emitted.sections[0].days, DAYS.slice(0, 5));
  editor.button("Add section").fire("click");
  assert.deepEqual(editor.emitted.sections[1].days, DAYS.slice(5));
  assert.equal(editor.field("section_1_days").value, "weekend");
  editor.field("section_1_sunday").checked = false;
  editor.field("section_1_sunday").fire("input");
  assert.deepEqual(editor.emitted.sections[1].days, ["saturday"]);
  assert.equal(editor.field("section_1_days").value, "custom");
  editor.button("Remove section", editor.section(1)).fire("click");
  assert.equal(editor.emitted.sections.length, 1);
});

test("periods use quarter-hour times, numeric half-degree temperatures and dynamic rows", () => {
  const editor = makeEditor();
  editor.button("Add period").fire("click");
  assert.equal(editor.emitted.sections[0].periods[1].time, "00:15");
  const hour = editor.field("section_0_period_1_time_hour");
  const minute = editor.field("section_0_period_1_time_minute");
  assert.equal(hour.inputMode, "numeric");
  assert.equal(hour.maxLength, 2);
  assert.deepEqual(minute.children.map((option) => option.value), ["00", "15", "30", "45"]);
  hour.value = "9"; hour.fire("input"); hour.fire("blur");
  minute.value = "00"; minute.fire("change");
  const temperature = editor.field("section_0_period_1_temperature");
  temperature.value = "22.5"; temperature.valueAsNumber = 22.5; temperature.validity = { badInput: false };
  temperature.fire("input");
  assert.deepEqual(editor.emitted.sections[0].periods, [
    { time: "00:00", temperature: 20 }, { time: "09:00", temperature: 22.5 },
  ]);
  const remove = descendants(editor.section(0)).filter((item) => item.tag === "button" && item.title === "Remove period");
  assert.equal(remove[0].disabled, true);
  remove[1].fire("click");
  assert.equal(editor.emitted.sections[0].periods.length, 1);
});

test("seven-section and 96-period limits disable additional rows", () => {
  const periods = Array.from({ length: 96 }, (_, slot) => ({
    time: `${String(Math.floor(slot / 4)).padStart(2, "0")}:${String(slot % 4 * 15).padStart(2, "0")}`, temperature: 20,
  }));
  const editor = makeEditor({ sections: DAYS.map((day) => ({ days: [day], periods })) });
  assert.equal(editor.button("Add section").disabled, true);
  assert.equal(editor.button("Add period", editor.section(0)).disabled, true);
});

test("adding a period appends after the last start without changing existing periods", () => {
  const periods = [
    { time: "00:00", temperature: 20 },
    { time: "09:00", temperature: 22.5 },
    { time: "20:00", temperature: 19 },
  ];
  const editor = makeEditor({ sections: [{ days: DAYS, periods }] });
  editor.button("Add period").fire("click");
  assert.deepEqual(editor.emitted.sections[0].periods, [
    ...periods, { time: "20:15", temperature: 19 },
  ]);
});

test("the final quarter-hour disables append even when earlier gaps remain", () => {
  const periods = [{ time: "00:00", temperature: 20 }, { time: "23:30", temperature: 19 }];
  const editor = makeEditor({ sections: [{ days: DAYS, periods }] });
  editor.button("Add period").fire("click");
  assert.equal(editor.emitted.sections[0].periods.at(-1).time, "23:45");
  assert.equal(editor.button("Add period").disabled, true);
});

test("unavailable schedule feedback and bindings disable dependent editors", () => {
  const editor = makeEditor({ settings: { cooling_available: false, schedule_available: false } });
  assert.equal(editor.field("cooling_enabled").disabled, true);
  assert.equal(editor.field("edit_schedule").disabled, true);
  assert.equal(editor.section(0), undefined);
});

test("enabling cooling reveals an independent direction selector without selecting a manual mode", () => {
  const editor = makeEditor({ edit: false, settings: { direction: "heating" } });
  assert.equal(editor.field("control_direction"), undefined);
  editor.field("cooling_enabled").checked = true;
  editor.field("cooling_enabled").fire("input");
  assert.equal(editor.field("control_direction").value, "unchanged");
  editor.field("control_direction").value = "cooling";
  editor.field("control_direction").fire("change");
  assert.equal(editor.emitted.control_direction, "cooling");
  assert.equal(editor.emitted.edit_schedule, false);
  assert.equal(editor.emitted.mode, undefined);
});

for (const language of ["en", "pl"]) {
  test(`${language}: limits are opt-in and update period bounds without changing targets`, () => {
    const editor = makeEditor({ language, settings: { limits_available: true } });
    assert.equal(editor.field("minimum"), undefined);
    editor.field("edit_limits").checked = true;
    editor.field("edit_limits").fire("input");
    assert.equal(editor.field("minimum").value, 10);
    assert.equal(editor.field("maximum").value, 30);
    const maximum = editor.field("maximum");
    maximum.valueAsNumber = 33; maximum.validity = { badInput: false };
    maximum.fire("input");
    assert.equal(editor.emitted.maximum, 33);
    assert.equal(editor.field("section_0_period_0_temperature").max, "33");
    assert.equal(editor.emitted.sections[0].periods[0].temperature, 20);
    editor.field("edit_limits").checked = false;
    editor.field("edit_limits").fire("input");
    assert.equal(editor.field("section_0_period_0_temperature").max, "30");
  });
}

for (const target of ["13", "18"]) {
  test(`typing ${target} keeps the same hour input and waits for the second digit`, () => {
    const editor = makeEditor({ sections: [{ days: DAYS, periods: [
      { time: "00:00", temperature: 20 }, { time: "09:15", temperature: 22 },
    ] }] });
    const root = editor.root;
    const hour = editor.field("section_0_period_1_time_hour");
    hour.fire("focus");
    assert.equal(hour.selectionStart, 0);
    assert.equal(hour.selectionEnd, 2);
    hour.value = "1";
    hour.fire("input"); hour.fire("change");
    editor.value = editor.emitted; // HA echoes value-changed back to the selector.
    assert.equal(hour.value, "1");
    assert.equal(editor.root, root);
    assert.equal(editor.field("section_0_period_1_time_hour"), hour);
    hour.value = target;
    hour.fire("input"); hour.fire("change"); hour.fire("blur");
    editor.value = editor.emitted;
    assert.equal(hour.value, target);
    assert.equal(editor.root, root);
    assert.equal(editor.emitted.sections[0].periods[1].time, `${target}:15`);
    assert.equal(editor.emitted.sections[0].periods[1].temperature, 22);
  });
}

test("single-digit hours are padded only on blur and invalid drafts are not hidden", () => {
  const editor = makeEditor();
  editor.button("Add period").fire("click");
  const hour = editor.field("section_0_period_1_time_hour");
  hour.value = "9"; hour.fire("input");
  assert.equal(hour.value, "9");
  assert.equal(editor.emitted.sections[0].periods[1].time, "09:15");
  hour.fire("blur");
  assert.equal(hour.value, "09");
  for (const invalid of ["", "24", "99", "a", "-1"]) {
    hour.value = invalid; hour.fire("input"); hour.fire("blur");
    assert.equal(editor.emitted.sections[0].periods[1].time, `${invalid}:15`);
    assert.equal(editor.button("Add period").disabled, true);
  }
});

test("editing time preserves row positions, updates append availability and uses the latest end", () => {
  const editor = makeEditor({ sections: [{ days: DAYS, periods: [
    { time: "00:00", temperature: 20 }, { time: "09:15", temperature: 22 },
    { time: "18:00", temperature: 19 },
  ] }] });
  const root = editor.root;
  const hour = editor.field("section_0_period_1_time_hour");
  const minute = editor.field("section_0_period_1_time_minute");
  hour.value = "23"; hour.fire("input"); hour.fire("blur");
  minute.value = "45"; minute.fire("change");
  assert.equal(editor.root, root);
  assert.equal(editor.button("Add period").disabled, true);
  assert.equal(editor.emitted.sections[0].periods[1].temperature, 22);
  minute.value = "30"; minute.fire("change");
  assert.equal(editor.button("Add period").disabled, false);
  editor.button("Add period").fire("click");
  assert.deepEqual(editor.emitted.sections[0].periods, [
    { time: "00:00", temperature: 20 }, { time: "18:00", temperature: 19 },
    { time: "23:30", temperature: 22 }, { time: "23:45", temperature: 22 },
  ]);
});
