odoo.define('yousentech_car_appointments.dashboard', function (require) {
'use strict';
var AbstractAction = require('web.AbstractAction');
var core = require('web.core');
var qweb = core.qweb;

var STORAGE_KEY = 'ycc_manager_dashboard_v2';
function loadPrefs() {
    try { return JSON.parse(window.localStorage.getItem(STORAGE_KEY) || '{}') || {}; } catch (e) { return {}; }
}
function savePrefs(prefs) {
    try { window.localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs)); } catch (e) { /* storage unavailable */ }
}

var Dashboard = AbstractAction.extend({
    events: {
        'click .ycc-dash-tab': '_onTab',
        'change .ycc-dash-branch': '_onBranch',
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
        this.branchId = prefs.branchId || false;
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
        // Only the live "today" tab refreshes itself; analysis tabs refresh on demand.
        this._timer = window.setInterval(function () {
            if (self._alive && self.tab === 'today' && !document.hidden && self.$el.is(':visible')) {
                self._load(true);
            }
        }, 30000);
        return this._super.apply(this, arguments).then(function () { return self._load(); });
    },
    destroy: function () {
        this._alive = false;
        if (this._timer) { window.clearInterval(this._timer); this._timer = null; }
        return this._super.apply(this, arguments);
    },
    _savePrefs: function () {
        savePrefs({tab: this.tab, branchId: this.branchId, mode: this.mode, compare: this.compare});
    },
    _load: function (silent) {
        var self = this;
        if (this._busy) { this._queued = true; return this._busy; }
        if (!silent) { this.$el.addClass('ycc-dash-loading'); }
        this._busy = this._rpc({
            model: 'ycc.dashboard',
            method: 'get_dashboard_data',
            args: [this.tab, {branch_id: this.branchId || false, mode: this.mode,
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
            if (self.branchId) { self.branchId = false; self._savePrefs(); self._queued = true; return; }
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
    _onBranch: function (ev) {
        var value = ev.currentTarget.value;
        this.branchId = value ? parseInt(value, 10) : false;
        this._savePrefs();
        this._load();
    },
    _onBranchShortcut: function (ev) {
        ev.preventDefault();
        var id = parseInt(ev.currentTarget.getAttribute('data-branch'), 10);
        if (!id) { return; }
        this.branchId = this.branchId === id ? false : id;
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
