import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync('web/dashboard_ui/js/30_modules.js', 'utf8');
const start = source.indexOf('function securityMultiPickerMarkup(');
const end = source.indexOf('async function renderSecurity()', start);
assert.ok(start > 0 && end > start, 'Fonctions du sélecteur absentes');

class MockElement {
  constructor({ classes = [], text = '' } = {}) {
    this.children = [];
    this.listeners = {};
    this.classNames = new Set(classes);
    this.classList = {
      add: (...keys) => keys.forEach(key => this.classNames.add(key)),
      remove: (...keys) => keys.forEach(key => this.classNames.delete(key)),
      contains: key => this.classNames.has(key),
      toggle: (key, force) => {
        const add = force === undefined ? !this.classNames.has(key) : Boolean(force);
        if (add) this.classNames.add(key);
        else this.classNames.delete(key);
        return add;
      },
    };
    this.attributes = {};
    this.textContent = text;
    this.value = '';
    this.isConnected = true;
    this.lookup = {};
    this.options = [];
    this.changeEvents = 0;
    this.focused = false;
  }
  appendChild(element) { this.children.push(element); return element; }
  replaceChildren(...elements) { this.children = elements; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name]; }
  addEventListener(event, callback) { (this.listeners[event] ||= []).push(callback); }
  removeEventListener(event, callback) {
    this.listeners[event] = (this.listeners[event] || []).filter(fn => fn !== callback);
  }
  dispatchEvent(event) {
    if (event.type === 'change') this.changeEvents += 1;
    this.fire(event.type, event);
  }
  fire(type, event = {}) { (this.listeners[type] || []).forEach(callback => callback(event)); }
  focus() { this.focused = true; }
  querySelector(selector) { return this.lookup[selector] || null; }
  contains(target) { return target === this || Object.values(this.lookup).includes(target); }
}

const document = new MockElement();
document.createElement = () => new MockElement();
const state = {};
const context = {
  document, state,
  Event: class Event { constructor(type) { this.type = type; } },
  esc: value => String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;'),
};
vm.createContext(context);
vm.runInContext(
  source.slice(start, end) + '\nglobalThis.bind = bindSecurityMultiPickers;\nglobalThis.markup = securityMultiPickerMarkup;',
  context
);
assert.ok(context.markup('roles', '<option>OK</option>', 'Chercher', 'Rôles').includes('data-security-chips'));
assert.ok(context.markup('roles', '', '<danger>', 'Rôles').includes('&lt;danger&gt;'));

function makePicker(id, records) {
  const widget = new MockElement();
  const select = new MockElement();
  select.id = id;
  select.options = records.map(([value, label, selected]) => ({
    value, textContent: label, selected: Boolean(selected), disabled: false,
  }));
  const trigger = new MockElement();
  const triggerText = new MockElement();
  const chips = new MockElement();
  const search = new MockElement();
  const choices = new MockElement();
  const popup = new MockElement({ classes:['hidden'] });
  const count = new MockElement();
  const done = new MockElement();
  widget.lookup = {
    'select[multiple]':select,
    '[data-security-trigger]':trigger,
    '[data-security-trigger-text]':triggerText,
    '[data-security-chips]':chips,
    '[data-security-search]':search,
    '[data-security-options]':choices,
    '[data-security-popover]':popup,
    '[data-security-visible-count]':count,
    '[data-security-done]':done,
  };
  return {widget, select, trigger, triggerText, chips, search, choices, popup, count, done};
}
const roles = makePicker('securityPolicyBypassRoles', [
  ['101', '@💠 Owner', true],
  ['102', '@Modérateurs', false],
  ['103', '@🤖 Bot', false],
]);
const channels = makePicker('securityPolicyStrictChannels', [
  ['201', '#💠 trade', true],
  ['202', '#🟠 giveaway', true],
  ['203', '#général', false],
]);
const root = new MockElement();
root.querySelectorAll = selector => selector === '[data-security-multi]' ? [roles.widget, channels.widget] : [];
let changed = 0;
context.bind(root, () => { changed += 1; });

assert.equal(roles.triggerText.textContent, '1 rôle sélectionné');
assert.equal(channels.triggerText.textContent, '2 salons stricts sélectionnés');
assert.equal(roles.chips.children[0].children[0].textContent, '@💠 Owner');
assert.equal(channels.chips.children.length, 2);

roles.trigger.fire('click');
assert.equal(roles.popup.classList.contains('hidden'), false);
assert.equal(roles.trigger.getAttribute('aria-expanded'), 'true');
assert.equal(roles.search.focused, true);
const moderatorChoice = roles.choices.children[1];
assert.equal(moderatorChoice.getAttribute('aria-checked'), 'false');
moderatorChoice.fire('click');
assert.equal(roles.select.options[1].selected, true);
assert.equal(roles.chips.children.length, 2);
assert.equal(roles.choices.children[1].getAttribute('aria-checked'), 'true');

roles.search.value = 'modér';
roles.search.fire('input');
assert.equal(roles.choices.children.length, 1);
assert.equal(roles.choices.children[0].children[1].textContent, '@Modérateurs');

roles.chips.children[1].children[1].fire('click');
assert.equal(roles.select.options[1].selected, false);
assert.equal(roles.chips.children.length, 1);

channels.trigger.fire('click');
assert.equal(roles.popup.classList.contains('hidden'), true);
assert.equal(channels.popup.classList.contains('hidden'), false);
channels.popup.fire('keydown', {key:'Escape', preventDefault() {}});
assert.equal(channels.popup.classList.contains('hidden'), true);
assert.equal(channels.trigger.focused, true);

assert.equal(changed, 2);
assert.equal(roles.select.changeEvents, 2);
console.log('PASS Multi-sélecteurs : rôles, salons, recherche, retrait, Escape et données.');
