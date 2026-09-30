/**
 * GoHighLevel workflow email stats -> Google Sheets, one click.
 *
 * Menu: "GHL Report" -> "Set API token", "Set Location ID", "Refresh report", "Schedule monthly refresh".
 * Data comes from the HighLevel Email API v3 (Version: v3), scopes on the Private Integration token:
 *   emails/campaigns.readonly, emails/stats.readonly.
 * The token is stored in the script's user properties, never in a cell.
 */

var BASE_URL = 'https://services.leadconnectorhq.com';
var PAGE_SIZE = 20;
var COUNT_FIELDS = ['sent', 'accepted', 'delivered', 'opened', 'clicked', 'replied', 'unsubscribed',
  'complained', 'permanentFail', 'temporaryFail', 'rejected', 'failed'];
var RATE_FIELDS = ['openRate', 'clickRate', 'replyRate', 'unsubscribeRate', 'complaintRate', 'bounceRate'];
var HEADER = ['Workflow', 'Step', 'Subject', 'From', 'Sent', 'Accepted', 'Delivered', 'Opened', 'Clicked',
  'Replied', 'Unsubscribed', 'Complained', 'Hard bounces', 'Soft bounces', 'Rejected', 'Failed',
  'Open rate %', 'Click rate %', 'Reply rate %', 'Unsubscribe rate %', 'Complaint rate %', 'Bounce rate %'];

// ---------- menu ----------

function onOpen() {
  SpreadsheetApp.getUi().createMenu('GHL Report')
    .addItem('Refresh report', 'refreshReport')
    .addSeparator()
    .addItem('Set API token', 'setToken')
    .addItem('Set Location ID', 'setLocationId')
    .addItem('Schedule monthly refresh', 'scheduleMonthly')
    .addItem('Remove schedule', 'removeSchedule')
    .addToUi();
}

function setToken() {
  var ui = SpreadsheetApp.getUi();
  var r = ui.prompt('GHL Private Integration token',
    'Sub-account Settings > Private Integrations > New. Scopes: emails/campaigns.readonly and emails/stats.readonly.',
    ui.ButtonSet.OK_CANCEL);
  if (r.getSelectedButton() !== ui.Button.OK) return;
  PropertiesService.getUserProperties().setProperty('GHL_TOKEN', r.getResponseText().trim());
  ui.alert('Token saved in your Google account (script properties), not in the sheet.');
}

function setLocationId() {
  var ui = SpreadsheetApp.getUi();
  var r = ui.prompt('Location (sub-account) ID',
    'Sub-account Settings > Business Profile > Location ID (about 20 characters).', ui.ButtonSet.OK_CANCEL);
  if (r.getSelectedButton() !== ui.Button.OK) return;
  PropertiesService.getUserProperties().setProperty('GHL_LOCATION', r.getResponseText().trim());
  ui.alert('Location ID saved.');
}

function scheduleMonthly() {
  removeSchedule();
  ScriptApp.newTrigger('refreshReport').timeBased().onMonthDay(1).atHour(6).create();
  SpreadsheetApp.getUi().alert('The report will refresh on the 1st of every month at 06:00 (your Google time zone).');
}

function removeSchedule() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'refreshReport') ScriptApp.deleteTrigger(t);
  });
}

// ---------- main ----------

function refreshReport() {
  var props = PropertiesService.getUserProperties();
  var token = props.getProperty('GHL_TOKEN');
  var location = props.getProperty('GHL_LOCATION');
  if (!token || !location) {
    throw new Error('Set the API token and the Location ID first (menu GHL Report).');
  }
  var api = makeApi(token, location);
  var result = collectRows(api);
  writeReport(result);
}

function makeApi(token, location) {
  return {
    location: location,
    get: function (path, params) {
      var url = BASE_URL + path + (params ? '?' + Object.keys(params).map(function (k) {
        return encodeURIComponent(k) + '=' + encodeURIComponent(params[k]);
      }).join('&') : '');
      var resp = UrlFetchApp.fetch(url, {
        method: 'get',
        headers: { Authorization: 'Bearer ' + token, Version: 'v3', Accept: 'application/json' },
        muteHttpExceptions: true
      });
      Utilities.sleep(120); // stay under 100 requests per 10 seconds
      var code = resp.getResponseCode();
      var body = resp.getContentText();
      return { code: code, json: code === 200 ? JSON.parse(body) : null, body: body };
    }
  };
}

/** Pure: walks workflows -> steps -> stats. `api.get(path, params)` returns {code, json, body}. */
function collectRows(api) {
  var rows = [];
  var errors = [];
  var workflows = listPaged(api, '/emails/locations/' + api.location + '/campaigns/workflows', { status: 'published' });
  var steps = 0;
  workflows.forEach(function (wf) {
    var d = api.get('/emails/locations/' + api.location + '/campaigns/workflows/' + wf.id);
    if (d.code !== 200) { errors.push('workflow ' + wf.name + ': HTTP ' + d.code + ' ' + d.body); return; }
    var candidates = [d.json.sourceId || wf.sourceId, wf.id];
    (d.json.subSources || []).forEach(function (step) {
      steps += 1;
      var st = fetchStats(api, 'workflow-campaigns', candidates, step.id);
      if (!st.ok) { errors.push('step "' + step.name + '" in "' + wf.name + '": ' + st.error); return; }
      var n = normalizeStats(st.stats);
      rows.push([wf.name || wf.id, step.name || step.id, step.subject || '',
        [step.fromName, step.fromEmail].filter(Boolean).join(' ')]
        .concat(COUNT_FIELDS.map(function (k) { return n.counts[k]; }))
        .concat(RATE_FIELDS.map(function (k) { return n.rates[k]; })));
    });
  });
  return { rows: rows, errors: errors, workflows: workflows.length, steps: steps };
}

function listPaged(api, path, params) {
  var out = [];
  var offset = 0;
  while (true) {
    var p = {};
    Object.keys(params).forEach(function (k) { p[k] = params[k]; });
    p.limit = PAGE_SIZE; p.offset = offset;
    var r = api.get(path, p);
    if (r.code !== 200) throw new Error('HTTP ' + r.code + ' listing ' + path + ': ' + r.body);
    var items = r.json.campaigns || [];
    out = out.concat(items);
    offset += PAGE_SIZE;
    if (items.length < PAGE_SIZE || offset >= (r.json.total || 0)) break;
  }
  return out;
}

/** The spec says "Source ID"; the workflow object carries both sourceId and id, so try both. */
function fetchStats(api, source, candidates, subSourceId) {
  var last = 'no candidate ids';
  for (var i = 0; i < candidates.length; i++) {
    if (!candidates[i]) continue;
    var params = subSourceId ? { subSourceId: subSourceId } : null;
    var r = api.get('/emails/locations/' + api.location + '/campaigns/stats/' + source + '/' + candidates[i], params);
    if (r.code === 200) return { ok: true, stats: r.json.stats || {}, used: candidates[i] };
    last = 'HTTP ' + r.code + ' for ' + source + '/' + candidates[i];
    if (r.code === 401 || r.code === 403) break;
  }
  return { ok: false, error: last };
}

/** Pure: ints for every count, floats for every rate; rates computed when the API omits them. */
function normalizeStats(stats) {
  var counts = {};
  COUNT_FIELDS.forEach(function (k) { counts[k] = parseInt(stats[k] || 0, 10) || 0; });
  if (!counts.sent) counts.sent = counts.delivered + counts.accepted + counts.permanentFail + counts.temporaryFail;
  var pct = function (num, den) { return den ? Math.round(10000 * num / den) / 100 : 0; };
  var computed = {
    openRate: pct(counts.opened, counts.delivered),
    clickRate: pct(counts.clicked, counts.delivered),
    replyRate: pct(counts.replied, counts.delivered),
    unsubscribeRate: pct(counts.unsubscribed, counts.delivered),
    complaintRate: pct(counts.complained, counts.delivered),
    bounceRate: pct(counts.permanentFail + counts.temporaryFail, counts.sent)
  };
  var rates = {};
  RATE_FIELDS.forEach(function (k) {
    rates[k] = (stats[k] !== undefined && stats[k] !== null) ? Math.round(parseFloat(stats[k]) * 100) / 100 : computed[k];
  });
  return { counts: counts, rates: rates };
}

// ---------- sheet output ----------

function writeReport(result) {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName('Report') || ss.insertSheet('Report');
  sheet.clearContents();
  sheet.getRange(1, 1, 1, HEADER.length).setValues([HEADER]).setFontWeight('bold');
  if (result.rows.length) sheet.getRange(2, 1, result.rows.length, HEADER.length).setValues(result.rows);
  sheet.setFrozenRows(1);
  sheet.autoResizeColumns(1, 4);

  var info = ss.getSheetByName('Info') || ss.insertSheet('Info');
  info.clearContents();
  info.getRange(1, 1, 5, 2).setValues([
    ['Last refreshed', new Date()],
    ['Workflows', result.workflows],
    ['Email steps', result.steps],
    ['Rows written', result.rows.length],
    ['Errors', result.errors.length]
  ]);
  if (result.errors.length) {
    info.getRange(7, 1).setValue('Errors').setFontWeight('bold');
    info.getRange(8, 1, result.errors.length, 1).setValues(result.errors.map(function (e) { return [e]; }));
  }
  SpreadsheetApp.getUi().alert('Done: ' + result.rows.length + ' email steps from ' + result.workflows +
    ' workflows. ' + (result.errors.length ? result.errors.length + ' errors listed on the Info sheet.' : 'No errors.'));
}
