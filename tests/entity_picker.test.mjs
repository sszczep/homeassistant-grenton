import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const component = new URL("../custom_components/homeassistant_grenton/", import.meta.url);
const source = readFileSync(new URL("frontend/scene-editor.js", component), "utf8");
const ids = ["binary_sensor.window", "sensor.temperature", "sensor.humidity", "switch.heater"];

class Element {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this.dataset = {};
    this.listeners = {};
    this.isConnected = true;
  }
  append(...children) { this.children.push(...children); }
  addEventListener(name, listener) { this.listeners[name] = listener; }
  fire(name, detail) {
    const event = { detail, stopPropagation() { this.stopped = true; } };
    this.listeners[name]?.(event);
    return event;
  }
}

function descendants(element) {
  return [element, ...element.children.flatMap(descendants)];
}

function picker(language = "en", value) {
  const elements = new Map();
  vm.runInNewContext(source, {
    HTMLElement: class {}, structuredClone,
    CustomEvent: class { constructor(type, options) { this.type = type; Object.assign(this, options); } },
    document: { createElement: (tag) => new Element(tag) },
    customElements: {
      get: (name) => elements.get(name),
      define: (name, cls) => elements.set(name, cls),
    },
  });
  const editor = Object.create(elements.get("ha-selector-grenton_entity").prototype);
  const translations = JSON.parse(readFileSync(new URL(`translations/${language}.json`, component), "utf8")).selector;
  editor._selector = { grenton_entity: { include_entities: ids } };
  editor._hass = { language };
  editor._value = value;
  editor._localizeValue = (key) => key.split(".").reduce((node, part) => node?.[part], translations);
  editor._container = () => (editor.root = new Element("div"));
  editor.dispatchEvent = (event) => { editor.emitted = event.detail.value; };
  editor.field = (name) => descendants(editor.root).find((node) => node.dataset.field === name);
  editor.filter = (domain) => {
    editor.field("entity_type").value = domain;
    editor.field("entity_type").fire("change");
  };
  editor.visible = () => Array.from(editor.field("entity").selector.entity.include_entities);
  editor._render();
  return editor;
}

for (const language of ["en", "pl"]) {
  test(`${language}: defaults to all and lists only available entity types with translated labels`, () => {
    const editor = picker(language);
    const filter = editor.field("entity_type");
    assert.equal(filter.value, "all");
    assert.deepEqual(editor.visible(), ids);
    assert.equal(editor.field("entity").label, language === "en" ? "Entity" : "Encja");
    assert.deepEqual(filter.children.map((option) => option.value), ["all", "binary_sensor", "sensor", "switch"]);
    assert.deepEqual(filter.children.map((option) => option.textContent), language === "en"
      ? ["All entities", "Binary sensors", "Sensors", "Switches"]
      : ["Wszystkie encje", "Czujniki binarne", "Czujniki", "Przełączniki"]);
  });
}

test("filter changes update the native searchable picker immediately", () => {
  const editor = picker();
  editor.filter("sensor");
  assert.deepEqual(editor.visible(), ["sensor.temperature", "sensor.humidity"]);
  assert.equal(editor.field("entity").tag, "ha-selector");
  editor.filter("binary_sensor");
  assert.deepEqual(editor.visible(), ["binary_sensor.window"]);
  editor.filter("all");
  assert.deepEqual(editor.visible(), ids);
});

test("the form's explicit empty initial value renders all entities without selecting one", () => {
  const editor = picker("en", "");
  assert.equal(editor.field("entity_type").value, "all");
  assert.deepEqual(editor.visible(), ids);
  assert.equal(editor.field("entity").value, "");
  assert.equal(editor.field("entity").required, true);
});

test("rendering does not depend on HA component translations being loaded", () => {
  const editor = picker("pl");
  editor._hass.localize = () => { throw new Error("Component translation unavailable"); };
  editor._render();
  assert.equal(editor.field("entity_type").value, "all");
  assert.deepEqual(editor.visible(), ids);
});

test("changing filter preserves a visible selection and clears a hidden selection", () => {
  const editor = picker("en", "sensor.temperature");
  editor.filter("sensor");
  assert.equal(editor.field("entity").value, "sensor.temperature");
  assert.equal(editor.emitted, "sensor.temperature");
  editor.filter("switch");
  assert.equal(editor.field("entity").value, undefined);
  assert.equal(editor.emitted, undefined);
  editor.filter("all");
  assert.equal(editor.field("entity").value, undefined);
});

test("entity selection submits only its ID and rejects foreign or hidden entities", () => {
  const editor = picker();
  editor.filter("sensor");
  let event = editor.field("entity").fire("value-changed", { value: "sensor.humidity" });
  assert.equal(event.stopped, true);
  assert.equal(editor.emitted, "sensor.humidity");
  assert.equal(editor.value, "sensor.humidity");
  editor.field("entity").fire("value-changed", { value: "switch.heater" });
  assert.equal(editor.value, "sensor.humidity");
  editor.field("entity").fire("value-changed", { value: "sensor.foreign" });
  assert.equal(editor.value, "sensor.humidity");
  editor.field("entity").fire("value-changed", { value: "" });
  assert.equal(editor.value, undefined);
});

test("HA updates reach the native picker without rebuilding it or losing its filter", () => {
  const editor = picker();
  editor.filter("sensor");
  const native = editor.field("entity");
  const hass = { language: "en", states: { "sensor.humidity": { state: "42" } } };
  editor.hass = hass;
  assert.equal(editor.field("entity"), native);
  assert.equal(native.hass, hass);
  assert.equal(editor.field("entity_type").value, "sensor");
  editor._disabled = true;
  editor._render();
  assert.equal(editor.field("entity").disabled, true);
  assert.equal(editor.field("entity_type").disabled, true);
});
