odoo.define('yousentech_car_appointments.dashboard', function (require) {
'use strict';
var AbstractAction = require('web.AbstractAction');
var core = require('web.core');
var qweb = core.qweb;

var STORAGE_KEY = 'ycc_manager_dashboard_v3';
function loadPrefs() {
    try { return JSON.parse(window.localStorage.getItem(STORAGE_KEY) || '{}') || {}; } catch (e) { return {}; }
}
function savePrefs(prefs) {
    try { window.localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs)); } catch (e) { /* storage unavailable */ }
}

var Dashboard = AbstractAction.extend({
    events: {
        'click .ycc-dash-tab': '_onTab',
        'click .ycc-dash-branch-toggle': '_onBranchToggle',
        'change .ycc-dash-branch-all': '_onBranchAll',
        'change .ycc-dash-branch-cb': '_onBranchItem',
        'click .ycc-dash-branch-apply': '_onBranchApply',
        'click .ycc-dash-branch-cancel': '_closeBranchPanel',
        'click .ycc-dash-branch-panel': '_stop',
        'click .ycc-dash-flow': '_onFlow',
        'click .ycc-dash-cmp-toggle': '_onCompareBranches',
        'keydown [role="button"][data-open-model]': '_onOpenKey',
        'click .ycc-dash-mode': '_onMode',
        'click .ycc-dash-step': '_onStep',
        'change .ycc-dash-compare': '_onCompare',
        'click .ycc-dash-refresh': '_onRefresh',
        'click [data-branch]': '_onBranchShortcut',
        'click [data-open-model]': '_onOpen',
    },
    init: function () {
        this._super.apply(this, arguments);
        var prefs = loadPrefs();
        this.tab = ['today', 'journey', 'team'].indexOf(prefs.tab) !== -1 ? prefs.tab : 'today';
        this.branchIds = Array.isArray(prefs.branchIds) ? prefs.branchIds : [];
        this.flowMode = ['day', 'week', 'month'].indexOf(prefs.flowMode) !== -1 ? prefs.flowMode : 'day';
        this.compareBranches = !!prefs.compareBranches;
        this.mode = ['day', 'month', 'year'].indexOf(prefs.mode) !== -1 ? prefs.mode : 'month';
        this.compare = ['none', 'previous', 'last_year'].indexOf(prefs.compare) !== -1 ? prefs.compare : 'none';
        this.anchor = false;  // the current period by default; navigation is per session
        this.data = null;
    },
    start: function () {
        var self = this;
        this._alive = true;
        // Odoo's action container has a fixed height and does not scroll by itself.
        this.$el.addClass('ycc-dash-host');
        this._onDocClick = function () { self._closeBranchPanel(); };
        document.addEventListener('click', this._onDocClick);
        // Only the live "today" tab refreshes itself; analysis tabs refresh on demand.
        this._timer = window.setInterval(function () {
            if (self._alive && self.tab === 'today' && !document.hidden && self.$el.is(':visible')
                    && !self.$('.ycc-dash-branch-panel:visible').length) {
                self._load(true);
            }
        }, 30000);
        return this._super.apply(this, arguments).then(function () { return self._load(); });
    },
    destroy: function () {
        this._alive = false;
        if (this._timer) { window.clearInterval(this._timer); this._timer = null; }
        if (this._onDocClick) { document.removeEventListener('click', this._onDocClick); }
        return this._super.apply(this, arguments);
    },
    _savePrefs: function () {
        savePrefs({tab: this.tab, branchIds: this.branchIds, mode: this.mode, compare: this.compare, flowMode: this.flowMode, compareBranches: this.compareBranches});
    },
    _load: function (silent) {
        var self = this;
        if (this._busy) { this._queued = true; return this._busy; }
        if (!silent) { this.$el.addClass('ycc-dash-loading'); }
        this._busy = this._rpc({
            model: 'ycc.dashboard',
            method: 'get_dashboard_data',
            args: [this.tab, {branch_ids: this.branchIds, mode: this.mode, flow_mode: this.flowMode,
                              compare_branches: this.compareBranches,
                              anchor: this.anchor || false, compare: this.compare}],
        }).then(function (data) {
            if (!self._alive) { return; }
            var signature = JSON.stringify(_.omit(data, 'generated_at'));
            if (silent && signature === self._signature) { return; }
            self._signature = signature;
            self.data = data;
            self._render();
        }, function () {
            if (!self._alive) { return; }
            // A branch removed from the user's access: fall back to all branches once.
            if (self.branchIds.length) { self.branchIds = []; self._savePrefs(); self._queued = true; return; }
            if (!silent) {
                self.$el.html('<div class="ycc-dash" dir="rtl"><div class="ycc-dash-empty"><i class="fa fa-exclamation-triangle"></i> تعذر تحميل لوحة المؤشرات.</div></div>');
            }
        }).then(function () {
            self._busy = null;
            self.$el.removeClass('ycc-dash-loading');
            if (self._queued) { self._queued = false; return self._load(); }
        });
        return this._busy;
    },
    _render: function () {
        var scrollTop = this.$el.scrollTop();
        this.$el.html(qweb.render('ycc.Dashboard', {d: this.data, tab: this.tab}));
        this.$el.scrollTop(scrollTop);
    },
    _onTab: function (ev) {
        var tab = ev.currentTarget.getAttribute('data-tab');
        if (!tab || tab === this.tab) { return; }
        this.tab = tab;
        this._signature = null;
        this._savePrefs();
        this._load();
    },
    _stop: function (ev) { ev.stopPropagation(); },
    _onBranchToggle: function (ev) {
        ev.stopPropagation();
        this.$('.ycc-dash-branch-panel').toggle();
    },
    _closeBranchPanel: function () {
        if (this.$el) { this.$('.ycc-dash-branch-panel').hide(); }
    },
    _onBranchAll: function (ev) {
        this.$('.ycc-dash-branch-cb').prop('checked', ev.currentTarget.checked);
    },
    _onBranchItem: function () {
        var boxes = this.$('.ycc-dash-branch-cb');
        this.$('.ycc-dash-branch-all').prop('checked', boxes.length === boxes.filter(':checked').length);
    },
    _onBranchApply: function (ev) {
        ev.stopPropagation();
        var boxes = this.$('.ycc-dash-branch-cb');
        var checked = boxes.filter(':checked').map(function () { return parseInt(this.value, 10); }).get();
        // Nothing or everything ticked means all branches.
        this.branchIds = (!checked.length || checked.length === boxes.length) ? [] : checked;
        this._closeBranchPanel();
        this._savePrefs();
        this._load();
    },
    _onBranchShortcut: function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        var id = parseInt(ev.currentTarget.getAttribute('data-branch'), 10);
        if (!id) { return; }
        this.branchIds = (this.branchIds.length === 1 && this.branchIds[0] === id) ? [] : [id];
        this._savePrefs();
        this._load();
    },
    _onCompareBranches: function () {
        this.compareBranches = !this.compareBranches;
        // Comparing needs at least two branches: a single selected branch widens to all.
        if (this.compareBranches && this.branchIds.length === 1) { this.branchIds = []; }
        this._savePrefs();
        this._load();
    },
    _onOpenKey: function (ev) {
        if (ev.key === 'Enter' || ev.key === ' ') { this._onOpen(ev); }
    },
    _onFlow: function (ev) {
        var mode = ev.currentTarget.getAttribute('data-flow');
        if (!mode || mode === this.flowMode) { return; }
        this.flowMode = mode;
        this._savePrefs();
        this._load();
    },
    _onMode: function (ev) {
        var mode = ev.currentTarget.getAttribute('data-mode');
        if (!mode || mode === this.mode) { return; }
        this.mode = mode;
        this._savePrefs();
        this._load();
    },
    _onStep: function (ev) {
        var anchor = ev.currentTarget.getAttribute('data-anchor');
        if (!anchor) { return; }
        this.anchor = anchor;
        this._load();
    },
    _onCompare: function (ev) {
        this.compare = ev.currentTarget.value || 'none';
        this._savePrefs();
        this._load();
    },
    _onRefresh: function () {
        this._signature = null;
        this._load();
    },
    _onOpen: function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        var el = ev.currentTarget;
        var model = el.getAttribute('data-open-model');
        if (['ycc.appointment', 'wo.installation.order.mst'].indexOf(model) === -1) { return; }
        var id = parseInt(el.getAttribute('data-open-id'), 10);
        if (id) {
            return this.do_action({type: 'ir.actions.act_window', res_model: model, res_id: id,
                views: [[false, 'form']], view_mode: 'form', target: 'current'});
        }
        var raw = el.getAttribute('data-open-ids');
        if (raw === null) { return; }
        var ids = raw.split(',').filter(Boolean).map(function (x) { return parseInt(x, 10); });
        if (!ids.length) {
            this.do_notify('لا توجد سجلات', 'لا توجد سجلات لعرضها في هذا المؤشر.');
            return;
        }
        return this.do_action({type: 'ir.actions.act_window', name: el.getAttribute('data-open-title') || 'المواعيد',
            res_model: model, domain: [['id', 'in', ids]], views: [[false, 'list'], [false, 'form']],
            view_mode: 'list,form', target: 'current'});
    },
});

core.action_registry.add('ycc_manager_dashboard', Dashboard);
return Dashboard;
});
