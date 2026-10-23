'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const { JSDOM } = require('jsdom');

const script = fs.readFileSync(path.join(__dirname, '../../web/dashboard_ui/js/30_modules.js'), 'utf8');
const begin = script.indexOf('/* SentriX MultiPicker V2');
const close = script.indexOf('/* fin SentriX MultiPicker V2 */');
assert.ok(begin >= 0 && close > begin, 'The real MultiPicker helper must be in the unified dashboard source');
const helper = script.slice(begin, close + '/* fin SentriX MultiPicker V2 */'.length);

function setup() {
  const markup = [
    '<!doctype html><html><body>',
    '<div class="field"><label for="securityPolicyBypassRoles">Rôles autorisés</label>',
    '<select id="securityPolicyBypassRoles" multiple>',
    '<option value="111" selected>@Bots</option>',
    '<option value="222">@Modération</option>',
    '<option value="333">@Staff</option></select></div>',
    '<div class="field"><label for="securityPolicyStrictChannels">Salons stricts</label>',
    '<select id="securityPolicyStrictChannels" multiple>',
    '<option value="444" selected>#commandes</option>',
    '<option value="555">#sondages</option>',
    '<option value="666">#général</option></select></div>',
    '</body></html>'
  ].join('');
  const dom = new JSDOM(markup, { url: 'https://sentrix.example/app' });
  const document = dom.window.document;
  const context = { document, Event: dom.window.Event, console, $: id => document.getElementById(id) };
  vm.createContext(context);
  vm.runInContext(helper, context);
  context.mountSecurityMultiPicker('securityPolicyBypassRoles', 'roles');
  context.mountSecurityMultiPicker('securityPolicyStrictChannels', 'channels');
  return { dom, document, context };
}
function values(select) {
  return Array.from(select.selectedOptions).map(option => option.value);
}

test('existing roles and channels remain selected and visible', () => {
  const { document } = setup();
  const roles = document.getElementById('securityPolicyBypassRoles');
  const channels = document.getElementById('securityPolicyStrictChannels');
  assert.deepEqual(values(roles), ['111']);
  assert.deepEqual(values(channels), ['444']);
  assert.equal(document.querySelectorAll('.sx-multi-picker').length, 2);
  assert.equal(document.querySelectorAll('.sx-picker-chip').length, 2);
  assert.equal(channels.classList.contains('sx-picker-native'), true);
  assert.equal(document.querySelectorAll('select[multiple][size]').length, 0);
});

test('checkboxes select several Discord channels without Ctrl or Cmd', () => {
  const { document, dom } = setup();
  const select = document.getElementById('securityPolicyStrictChannels');
  let events = 0;
  select.addEventListener('change', () => events++);
  const root = select.nextElementSibling;
  const boxes = Array.from(root.querySelectorAll('input[type="checkbox"]'));
  assert.equal(boxes.length, 3);
  boxes[1].checked = true;
  boxes[1].dispatchEvent(new dom.window.Event('change', { bubbles: true }));
  boxes[2].checked = true;
  boxes[2].dispatchEvent(new dom.window.Event('change', { bubbles: true }));
  assert.deepEqual(values(select), ['444', '555', '666']);
  assert.equal(root.querySelector('.sx-picker-count').textContent, '3 salons sélectionnés');
  assert.equal(root.querySelector('.sx-picker-edited').hidden, false);
  assert.equal(events, 2);
});

test('removing a chip updates the real select used by the backend', () => {
  const { document } = setup();
  const select = document.getElementById('securityPolicyBypassRoles');
  const picker = select.nextElementSibling;
  const chip = picker.querySelector('.sx-picker-chip');
  assert.match(chip.textContent, /Bots/);
  chip.click();
  assert.deepEqual(values(select), []);
  assert.equal(picker.querySelector('.sx-picker-chip'), null);
  assert.equal(picker.querySelector('.sx-picker-edited').hidden, false);
});

test('search filters displayed options without deleting selected values', () => {
  const { document, dom } = setup();
  const select = document.getElementById('securityPolicyStrictChannels');
  const picker = select.nextElementSibling;
  const search = picker.querySelector('.sx-picker-search');
  search.value = 'general';
  search.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
  const rows = Array.from(picker.querySelectorAll('.sx-picker-option'));
  assert.deepEqual(rows.map(x => x.hidden), [true, true, false]);
  assert.deepEqual(values(select), ['444']);
  search.value = 'aucun salon';
  search.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
  assert.equal(picker.querySelector('.sx-picker-empty').hidden, false);
  assert.deepEqual(values(select), ['444']);
});

test('double mounting never duplicates picker widgets or event listeners', () => {
  const { document, context } = setup();
  context.mountSecurityMultiPicker('securityPolicyStrictChannels', 'channels');
  assert.equal(document.querySelectorAll('.sx-multi-picker').length, 2);
});

test('picker does not save without clicking the existing save button', () => {
  assert.ok(helper.includes("select.dispatchEvent(new Event('change'"));
  assert.equal(/\bgpost\s*\(/.test(helper), false);
  assert.ok(script.includes("const strictChannelIds = clearStrict ? [] : selectedValues($('securityPolicyStrictChannels'))"));
  assert.ok(script.includes("const roleIds = clearRoles ? [] : selectedValues($('securityPolicyBypassRoles'))"));
  assert.ok(script.includes("gpost('/security/filter-policies'"));
});
