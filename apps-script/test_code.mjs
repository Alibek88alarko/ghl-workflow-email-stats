// Runs the pure parts of Code.gs under Node with a fake API, so the Sheets logic is checked before it meets Google.
import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import vm from 'node:vm';

const src = readFileSync(new URL('./Code.gs', import.meta.url), 'utf8');
const ctx = { UrlFetchApp: {}, Utilities: { sleep() {} }, SpreadsheetApp: {}, PropertiesService: {}, ScriptApp: {}, console };
vm.createContext(ctx);
vm.runInContext(src + '\nthis.__x = { collectRows, normalizeStats, listPaged, fetchStats };', ctx);
const { collectRows, normalizeStats } = ctx.__x;

const LOC = 'loc1';
const workflows = Array.from({ length: 45 }, (_, i) => ({ id: `wf${i + 1}`, name: `Workflow ${i + 1}`, sourceId: `src${i + 1}`, status: 'published' }));
const steps = id => [
  { id: `${id}-s1`, name: 'Welcome', subject: 'Hi', fromName: 'Clinic', fromEmail: 'a@b.c' },
  { id: `${id}-s2`, name: 'Follow-up', subject: 'Again', fromName: 'Clinic', fromEmail: 'a@b.c' },
];
const calls = [];
const api = {
  location: LOC,
  get(path, params) {
    calls.push(path);
    const p = params || {};
    const m = path.match(/\/campaigns\/(workflows|stats\/workflow-campaigns)(?:\/([^/]+))?$/);
    if (path.endsWith('/campaigns/workflows')) {
      const off = +p.offset, lim = +p.limit;
      return { code: 200, json: { campaigns: workflows.slice(off, off + lim), total: workflows.length } };
    }
    if (m && m[1] === 'workflows') {
      const wf = workflows.find(w => w.id === m[2]);
      return wf ? { code: 200, json: { ...wf, subSources: steps(wf.id) } } : { code: 404, json: null, body: 'nf' };
    }
    if (m && m[1] === 'stats/workflow-campaigns') {
      const wf = workflows.find(w => w.sourceId === m[2]);      // real API wants sourceId
      if (!wf) return { code: 422, json: null, body: 'bad source' };
      if (!steps(wf.id).some(s => s.id === p.subSourceId)) return { code: 422, json: null, body: 'bad step' };
      return { code: 200, json: { stats: { delivered: 1000, opened: 250, clicked: 50, permanentFail: 10, temporaryFail: 5, accepted: 5 } } };
    }
    return { code: 404, json: null, body: 'no route ' + path };
  },
};

const r = collectRows(api);
assert.equal(r.workflows, 45);
assert.equal(r.steps, 90);
assert.equal(r.rows.length, 90);
assert.equal(r.errors.length, 0);
assert.equal(r.rows[0][0], 'Workflow 1');
assert.equal(r.rows[0][1], 'Welcome');
assert.equal(r.rows[0][4], 1020);           // sent computed = delivered + accepted + bounces
assert.equal(r.rows[0][16], 25);            // open rate %
assert.equal(r.rows[0][21], 1.47);          // bounce rate % = 15 / 1020
assert.equal(calls.filter(c => c.endsWith('/campaigns/workflows')).length, 3); // three pages of 20

const n = normalizeStats({ delivered: 200, opened: 50, openRate: 45 });
assert.equal(n.rates.openRate, 45);         // API rate kept
assert.equal(n.rates.clickRate, 0);
console.log('Code.gs logic: all checks passed (45 workflows, 90 steps, pagination, sourceId fallback, rates)');
