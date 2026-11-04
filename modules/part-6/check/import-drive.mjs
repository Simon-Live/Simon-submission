// Drives the Import screen and reads the files panel of the detail screen (docs/specs/catalog-contract.md
// AC-C08 DOM contract). One copy for check/check6-contract.mjs and staging/verify/import-screen.mjs.
// Waits are on locators and page functions, never on fixed sleeps; a control the screen does not have
// fails by name. `observer` is the harness observer (or null) that counts file inputs per screen.
import {
  byId, frames, screenVisible, tap, waitForPlayer,
} from './harness.mjs';

const ROW = '[data-testid="import-file"]';
const FILE_ROW = '[data-testid="entry-file"]';
const CATEGORY_LABEL = { exercise: 'Exercise', dance: 'Dance' };

// From the catalog: tap Import and wait for the Import screen.
export async function openImport(page, observer) {
  await tap(page, 'open-import');
  await screenVisible(page, observer, 'import');
}

// The file picker is the element with data-testid import-files or the file input inside it.
async function fileInput(page) {
  const box = byId(page, 'import-files');
  const tag = await box.evaluate((el) => el.tagName);
  return tag === 'INPUT' ? box : box.locator('input[type="file"]').first();
}

// Chooses files the way a person does with the picker; `uploads` are {name, mimeType, buffer}.
export async function dropFiles(page, uploads) {
  await (await fileInput(page)).setInputFiles(uploads);
}

export function importRows(page) {
  return page.$$eval(ROW, (els) => els.map((el) => ({
    kind: el.getAttribute('data-kind'),
    format: el.getAttribute('data-format'),
    error: el.getAttribute('data-error') === '1',
    text: el.textContent.replace(/\s+/g, ' ').trim(),
  })));
}

// Waits until the screen lists `count` files and has read each (a kind and format, or an error).
export async function waitForRows(page, count) {
  await page.waitForFunction(([selector, n]) => {
    const rows = [...document.querySelectorAll(selector)];
    return rows.length === n
      && rows.every((row) => row.getAttribute('data-error') === '1' || !!row.getAttribute('data-format'));
  }, [ROW, count]);
  await frames(page, 2);
  return importRows(page);
}

export async function fillName(page, name) {
  await byId(page, 'import-name').fill(name);
}

// The type field is a select, or a group of radios with labels; either way the person picks the word.
export async function chooseCategory(page, category) {
  const box = byId(page, 'import-category');
  const tag = await box.evaluate((el) => el.tagName);
  if (tag === 'SELECT') {
    await box.selectOption({ label: CATEGORY_LABEL[category] });
    return;
  }
  if (tag === 'INPUT') {
    await box.tap();
    return;
  }
  await box.locator('label', { hasText: new RegExp(`^\\s*${CATEGORY_LABEL[category]}\\s*$`) }).first().tap();
}

export async function categoryChosen(page) {
  const box = byId(page, 'import-category');
  const tag = await box.evaluate((el) => el.tagName);
  if (tag === 'SELECT') return box.evaluate((el) => el.selectedOptions[0].textContent.trim());
  return page.evaluate(() => {
    const checked = document.querySelector('[data-testid="import-category"] input:checked, input[data-testid="import-category"]:checked');
    if (!checked) return null;
    const label = checked.closest('label');
    return (label ? label.textContent : checked.value).trim();
  });
}

export function waitSaveEnabled(page) {
  return page.waitForFunction(() => {
    const button = document.querySelector('[data-testid="import-save"]');
    return !!button && !button.disabled;
  });
}

// The text the screen shows for a failed import, or null while it shows none.
export async function importErrorText(page) {
  const node = byId(page, 'import-error');
  if (!(await node.isVisible())) return null;
  return ((await node.textContent()) || '').trim();
}

// Taps Import and waits for the entry's detail screen, or throws the screen's own error message.
export async function saveImport(page, observer) {
  await tap(page, 'import-save');
  const outcome = await Promise.race([
    waitForPlayer(page, observer).then(() => 'opened'),
    byId(page, 'import-error').waitFor({ state: 'visible' }).then(() => 'error'),
  ]);
  if (outcome === 'error') {
    throw new Error(`Import failed, the screen says: "${await importErrorText(page)}"`);
  }
}

// ---------------------------------------------------------------- the detail screen's files panel

export async function filesPanel(page) {
  await byId(page, 'entry-files').waitFor({ state: 'visible' });
  return page.$$eval(FILE_ROW, (els) => els.map((el) => ({
    kind: el.getAttribute('data-kind'),
    format: el.getAttribute('data-format'),
    part: el.getAttribute('data-part'),
    state: el.getAttribute('data-state'),
    text: el.textContent.replace(/\s+/g, ' ').trim(),
  })));
}

export const rowOf = (rows, kind) => rows.find((r) => r.kind === kind) || null;

// The row as a short string for a witness or a failure message.
export const rowLine = (row) => (row ? `${row.kind}:${row.format || '-'}:part ${row.part || '-'}:${row.state}` : 'no row');
