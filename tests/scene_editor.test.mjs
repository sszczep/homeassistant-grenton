// Exercise the real row renderer with a small DOM substitute; no browser or
// frontend build dependencies are needed for these localization regressions.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const component = new URL("../custom_components/homeassistant_grenton/", import.meta.url);
const source = readFileSync(new URL("frontend/scene-editor.js", component), "utf8");

class Element {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this.dataset = {};
    this.listeners = {};
    this.isConnected = true;
  }
  append(...children) { this.children.push(...children); }
  setAttribute() {}
  addEventListener(name, listener) { this.listeners[name] = listener; }
  fire(name) { this.listeners[name]?.(); }
}

function descendants(element) {
  return [element, ...element.children.flatMap(descendants)];
}

for (const language of ["en", "pl"]) {
  test(`${language}: argument positions need no translation context and Float has a numeric control`, () => {
    const translations = JSON.parse(readFileSync(new URL(`translations/${language}.json`, component), "utf8")).selector;
    const selectors = new Map();
    vm.runInNewContext(source, {
      HTMLElement: class {},
      structuredClone,
      document: { createElement: (tag) => new Element(tag) },
      customElements: {
        get: (name) => selectors.get(name),
        define: (name, constructor) => selectors.set(name, constructor),
      },
    });
    const editor = Object.create(selectors.get("ha-selector-grenton_scene").prototype);
    editor._localizeValue = (key) => {
      const message = key.split(".").reduce((value, part) => value?.[part], translations);
      // HA's localizeValue callback provides no ICU interpolation values.
      if (message) assert.doesNotMatch(message, /\{[^}]+\}/);
      return message;
    };
    const root = new Element("div");
    editor._renderArguments(root, [
      { type: "float", value: 1.25 },
      { type: "number", value: 2 },
    ], () => {});
    const rendered = descendants(root);
    assert.deepEqual(rendered.filter((element) => element.tag === "strong").map((element) => element.textContent), ["Argument 1", "Argument 2"]);
    const typePicker = rendered.find((element) => element.dataset.field === "argument_0_type");
    assert.equal(typePicker.value, "float");
    const floatChoice = typePicker.children.find((option) => option.value === "float");
    assert.equal(floatChoice.textContent, language === "pl" ? "Liczba zmiennoprzecinkowa" : "Float");
    const floatInput = rendered.find((element) => element.dataset.field === "argument_0_value");
    assert.equal(floatInput.type, "number");
    assert.equal(floatInput.step, "any");
    assert.equal(floatInput.value, 1.25);
  });
}


function actionEditor(mode, initial) {
  const selectors = new Map();
  vm.runInNewContext(source, {
    HTMLElement: class {}, structuredClone,
    CustomEvent: class { constructor(name, details) { this.type = name; Object.assign(this, details); } },
    document: { createElement: (tag) => new Element(tag) },
    customElements: {
      get: (name) => selectors.get(name),
      define: (name, constructor) => selectors.set(name, constructor),
    },
  });
  const editor = Object.create(selectors.get("ha-selector-grenton_scene").prototype);
  editor._selector = { grenton_scene: { mode, editable_value: true, clus: [{ value: "clu1", label: "Main" }] } };
  editor._value = structuredClone(initial);
  editor._container = () => (editor.root = new Element("div"));
  editor.shadowRoot = { querySelectorAll: () => [], querySelector: () => null };
  editor.dispatchEvent = (event) => { editor.emitted = event.detail.value; };
  editor._render();
  editor.field = (name) => descendants(editor.root).find((item) => item.dataset.field === name);
  editor.button = (label) => descendants(editor.root).find((item) => item.tag === "button" && item.textContent === label);
  return editor;
}

test("state form offers only attribute/variable and switches target fields without a set value", () => {
  const editor = actionEditor("state", { call_type: "ATTRIBUTE", clu_id: "clu1", object_name: "DOUT", index: "0" });
  assert.deepEqual(editor.field("call_type").children.map((option) => option.value), ["ATTRIBUTE", "VARIABLE"]);
  assert.equal(editor.field("object_name").value, "DOUT");
  assert.equal(editor.field("index").value, "0");
  assert.equal(editor.field("value"), undefined);
  editor.field("call_type").value = "VARIABLE";
  editor.field("call_type").fire("change");
  assert.equal(editor.field("object_name"), undefined);
  assert.equal(editor.field("index"), undefined);
  assert.ok(editor.field("variable_name"));
  assert.equal(editor.field("value"), undefined);
  editor.field("variable_name").value = "OfficeState";
  editor.field("variable_name").fire("input");
  assert.equal(editor.emitted.variable_name, "OfficeState");
});

test("on/off action form shows set values or dynamically editable argument rows", () => {
  const editor = actionEditor("action", { call_type: "ATTRIBUTE", clu_id: "clu1", object_name: "DOUT", index: "0", value: "1" });
  assert.equal(editor.field("call_type").children.length, 4);
  assert.equal(editor.field("value").value, "1");
  editor.field("value").value = "0";
  editor.field("value").fire("input");
  assert.equal(editor.emitted.value, "0");
  editor.field("call_type").value = "METHOD";
  editor.field("call_type").fire("change");
  assert.equal(editor.field("value"), undefined);
  assert.ok(editor.field("index"));
  editor.button("Add argument").fire("click");
  assert.equal(editor.field("argument_0_type").value, "string");
  editor.field("argument_0_type").value = "float";
  editor.field("argument_0_type").fire("change");
  assert.equal(editor.field("argument_0_value").type, "number");
  const input = editor.field("argument_0_value");
  input.value = "-1.25"; input.valueAsNumber = -1.25; input.validity = { badInput: false };
  input.fire("input");
  assert.equal(editor.emitted.arguments[0].value, -1.25);
  editor.button("Add argument").fire("click");
  assert.ok(editor.field("argument_1_value"));
  editor.button("Remove").fire("click");
  assert.equal(editor.emitted.arguments.length, 1);
  editor.button("Remove").fire("click");
  assert.equal(editor.emitted.arguments.length, 0);
  editor.field("call_type").value = "SCRIPT";
  editor.field("call_type").fire("change");
  assert.equal(editor.field("index"), undefined);
  assert.ok(editor.button("Add argument"));
  editor.field("call_type").value = "VARIABLE";
  editor.field("call_type").fire("change");
  assert.ok(editor.field("variable_name"));
  assert.ok(editor.field("value"));
  assert.equal(editor.field("object_name"), undefined);
  assert.equal(editor.button("Add argument"), undefined);
});
