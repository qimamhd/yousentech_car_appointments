# -*- coding: utf-8 -*-
"""Manager dashboard (V6.65): read-only indicators for appointments and users.

All figures are computed on request with the requesting user's normal access
rights and branch record rules. Nothing here writes to appointments or orders.
Team performance is attributed to the booking creator (create_uid).
"""
from datetime import datetime, timedelta, time as dtime
import pytz
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError

from .appointment import CANCEL_REASONS, NO_SHOW_REASONS

OPEN_STATES = ['provisional', 'contacting', 'confirmed', 'done', 'installation_created',
               'postponed', 'inspection_completed']
FOLLOWUP_STATES = ['provisional', 'contacting', 'confirmed', 'postponed']
REACHED_CONFIRMED = ('confirmed', 'done', 'installation_created', 'no_show', 'inspection_completed')
ACTIVE_ORDER_STATES = ['confirm', 'under_checking', 'work_order', 'execute_request',
                       'execute_started', 'return_to_modify']
COMPLETED_ORDER_STATES = ('execute_completed', 'complete_work')

# Visual keys shared with the dashboard front end (colors live in SCSS).
STAGE_LABELS = {
    'provisional': 'مبدئي', 'confirmed': 'مؤكد', 'done': 'وصلت',
    'waiting': 'بانتظار أمر', 'order': 'أمر تركيب', 'noshow': 'لم يحضر',
}
WEEKDAYS_SAT_FIRST = [(5, 'السبت'), (6, 'الأحد'), (0, 'الاثنين'), (1, 'الثلاثاء'),
                      (2, 'الأربعاء'), (3, 'الخميس'), (4, 'الجمعة')]
MODES = [('day', 'يومي'), ('month', 'شهري'), ('year', 'سنوي')]
COMPARES = [('none', 'بدون مقارنة'), ('previous', 'الفترة السابقة'), ('last_year', 'نفس الفترة من السنة السابقة')]
AR_MONTHS = ['يناير', 'فبراير', 'مارس', 'أبريل', 'مايو', 'يونيو', 'يوليو', 'أغسطس',
             'سبتمبر', 'أكتوبر', 'نوفمبر', 'ديسمبر']
AR_DAYS = ['الاثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة', 'السبت', 'الأحد']
INDICATOR_DEFS = [
    ('late_arrival', 'تأخر الوصول', 'fa-clock-o'), ('late_delivery', 'تأخر التسليم', 'fa-calendar-times-o'),
    ('open_invoices', 'فواتير مفتوحة', 'fa-file-text-o'), ('checks', 'تشييك', 'fa-stethoscope'),
    ('contacting', 'جاري التواصل', 'fa-phone'), ('provisional', 'حجز مبدئي', 'fa-calendar-o'),
    ('no_show', 'لم يحضر', 'fa-user-times'), ('postponed', 'تم تأجيله', 'fa-calendar-plus-o'),
    ('completed', 'تم الإنجاز', 'fa-check-circle'), ('invoice_closed', 'إقفال الفاتورة', 'fa-check-square-o'),
]


def _add_months(day, months):
    index = day.year * 12 + day.month - 1 + months
    return day.replace(year=index // 12, month=index % 12 + 1, day=1)


def _shift_year(day, years):
    try:
        return day.replace(year=day.year + years)
    except ValueError:  # 29 February
        return day.replace(year=day.year + years, day=28)


def _delta(cur, prev, better='up', unit='', points=False):
    """Comparison badge: absolute change (or percentage points) with direction."""
    if prev is None or cur is None:
        return None
    diff = cur - prev
    if isinstance(diff, float):
        diff = round(diff, 1)
    if not diff:
        return {'text': 'بدون تغيير', 'dir': 'flat', 'good': 'flat', 'prev': prev}
    sign = '+' if diff > 0 else '−'
    value = abs(diff)
    value = int(value) if float(value).is_integer() else value
    text = '%s%s%s' % (sign, value, ' نقطة' if points else unit)
    if not points and not unit and prev:
        text += ' (%s%s%%)' % (sign, int(round(abs(diff) * 100.0 / prev)))
    good = 'good' if (diff > 0) == (better == 'up') else 'bad'
    return {'text': text, 'dir': 'up' if diff > 0 else 'down', 'good': good, 'prev': prev}


def _fmt_hours(value):
    n = int(round((value or 0) * 60))
    return '%02d:%02d' % (n // 60, n % 60)


def _pct(part, whole):
    return int(round(part * 100.0 / whole)) if whole else 0


def _avg(values):
    values = [v for v in values if v is not None]
    return (sum(values) / len(values)) if values else None


class YCCDashboard(models.AbstractModel):
    _name = 'ycc.dashboard'
    _description = 'لوحة مؤشرات مدير المواعيد'

    # ------------------------------------------------------------------ helpers
    def _check_manager(self):
        if not self.env['ycc.appointment']._ycc_manager():
            raise AccessError(_('لوحة المؤشرات متاحة لمدير المواعيد فقط.'))

    def _tz(self):
        name = self.env.user.tz or self.env.company.partner_id.tz or 'Asia/Riyadh'
        try:
            return pytz.timezone(name)
        except pytz.UnknownTimeZoneError:
            return pytz.UTC

    def _now(self):
        now_utc = fields.Datetime.now()
        return now_utc, pytz.UTC.localize(now_utc).astimezone(self._tz())

    def _local(self, dt_utc):
        if not dt_utc:
            return None
        return pytz.UTC.localize(fields.Datetime.to_datetime(dt_utc)).astimezone(self._tz())

    def _utc_bound(self, day):
        """Local midnight of `day` as a naive UTC datetime (for stored datetimes)."""
        local = self._tz().localize(datetime.combine(day, dtime.min))
        return local.astimezone(pytz.UTC).replace(tzinfo=None)

    def _period(self, mode, anchor):
        """[start, end) and a label for the chosen granularity around anchor."""
        if mode == 'day':
            start = anchor
            end = anchor + timedelta(days=1)
            label = '%s %s %s %s' % (AR_DAYS[anchor.weekday()], anchor.day, AR_MONTHS[anchor.month - 1], anchor.year)
        elif mode == 'year':
            start = anchor.replace(month=1, day=1)
            end = start.replace(year=start.year + 1)
            label = 'سنة %s' % start.year
        else:
            start = anchor.replace(day=1)
            end = _add_months(start, 1)
            label = '%s %s' % (AR_MONTHS[start.month - 1], start.year)
        return start, end, label

    def _step(self, mode, anchor, step):
        if mode == 'day':
            return anchor + timedelta(days=step)
        if mode == 'year':
            return _shift_year(anchor.replace(month=1, day=1), step)
        return _add_months(anchor, step)

    def _compare_anchor(self, mode, anchor, compare):
        if compare == 'previous':
            return self._step(mode, anchor, -1)
        if compare == 'last_year':
            return _shift_year(anchor, -1)
        return None

    def _configs(self, branch_id):
        Branch = self.env['ycc.branch']
        allowed = Branch._ycc_allowed_custom_branches()
        all_cfg = Branch.search([('active', '=', True), ('branch_id', 'in', allowed.ids)], order='id')
        selected = all_cfg
        if branch_id:
            selected = all_cfg.filtered(lambda c: c.id == int(branch_id))
            if not selected:
                raise AccessError(_('الفرع غير مسموح للمستخدم.'))
        return all_cfg, selected

    def _safe_periods(self, appt):
        try:
            return appt._covered_periods()
        except ValidationError:
            return [(fields.Date.to_string(appt.date), appt.slot_id)] if appt.date and appt.slot_id else []

    @staticmethod
    def _stage_key(appt):
        if appt.state == 'no_show':
            return 'noshow'
        if appt.installation_order_id or appt.state in ('installation_created', 'inspection_completed'):
            return 'order'
        if appt.state == 'done':
            return 'done' if appt.is_check_only else 'waiting'
        if appt.state in ('confirmed', 'postponed'):
            return 'confirmed'
        return 'provisional'

    def _orders_model(self):
        return self.env['wo.installation.order.mst'] if 'wo.installation.order.mst' in self.env else None

    # --------------------------------------------------------------- entry point
    @api.model
    def get_dashboard_data(self, tab='today', params=None):
        self._check_manager()
        params = params or {}
        now_utc, local_now = self._now()
        today = local_now.date()
        all_cfg, selected = self._configs(params.get('branch_id'))
        mode = params.get('mode') if params.get('mode') in dict(MODES) else 'month'
        compare = params.get('compare') if params.get('compare') in dict(COMPARES) else 'none'
        try:
            anchor = fields.Date.to_date(params.get('anchor')) if params.get('anchor') else today
        except (ValueError, TypeError):
            anchor = today
        start, end, label = self._period(mode, anchor)
        cmp_anchor = self._compare_anchor(mode, anchor, compare)
        cmp_period = self._period(mode, cmp_anchor) if cmp_anchor else None
        data = {
            'tab': tab,
            'branches': [{'id': c.id, 'name': c.branch_id.display_name} for c in all_cfg],
            'branch_id': int(params['branch_id']) if params.get('branch_id') else False,
            'modes': [{'key': k, 'label': v} for k, v in MODES],
            'compares': [{'key': k, 'label': v} for k, v in COMPARES],
            'mode': mode, 'compare': compare,
            'anchor': fields.Date.to_string(anchor),
            'prev_anchor': fields.Date.to_string(self._step(mode, anchor, -1)),
            'next_anchor': fields.Date.to_string(self._step(mode, anchor, 1)),
            'is_current': start <= today < end,
            'period_label': label,
            'compare_label': cmp_period[2] if cmp_period else '',
            'today': fields.Date.to_string(today),
            'today_label': self._period('day', today)[2],
            'generated_at': local_now.strftime('%H:%M'),
        }
        if not all_cfg:
            data['empty'] = _('لا توجد فروع مهيأة لنظام المواعيد ضمن صلاحياتك.')
            return data
        if tab == 'journey':
            data.update(self._journey_data(selected, start, end, now_utc, cmp_period))
            data['indicators'] = self._indicators(selected, start, end, local_now)
        elif tab == 'team':
            data.update(self._team_data(selected, start, end, now_utc, cmp_period))
        else:
            data['tab'] = 'today'
            data.update(self._today_data(all_cfg, selected, now_utc, local_now))
            data['indicators'] = self._indicators(selected, today, today + timedelta(days=1), local_now)
        return data

    def _indicators(self, selected, start, end, local_now):
        """The calendar's customer-service indicators, from the shared model method."""
        items = self.env['ycc.appointment']._ycc_service_indicators(selected, start, end, local_now)
        result = []
        for key, title, icon in INDICATOR_DEFS:
            rows = items.get(key, [])
            if key in ('late_delivery', 'open_invoices', 'checks'):
                ids, model = sorted({r['order_id'] for r in rows if r['order_id']}), 'wo.installation.order.mst'
            else:
                ids, model = sorted({r['booking_id'] for r in rows if r['booking_id']}), 'ycc.appointment'
            result.append({'key': key, 'title': title, 'icon': icon, 'count': len(rows), 'ids': ids, 'model': model})
        return result

    # ---------------------------------------------------------------- tab: today
    def _today_data(self, all_cfg, selected, now_utc, local_now):
        Appt = self.env['ycc.appointment']
        Order = self._orders_model()
        today = local_now.date()
        today_s = fields.Date.to_string(today)
        occupying = {cfg.id: Appt._daily_occupied_appointments(cfg.id, today_s, now=now_utc) for cfg in all_cfg}
        sel_ids = selected.ids
        occ = Appt.browse()
        for cfg in selected:
            occ |= occupying[cfg.id]
        no_show_today = Appt.search([
            ('branch_id', 'in', sel_ids), ('state', '=', 'no_show'), ('date', '<=', today_s),
            '|', '&', ('end_date', '=', False), ('date', '=', today_s), ('end_date', '>=', today_s)])
        capacity = sum(selected.mapped('capacity'))
        booked = len(occ)
        provisional = len(occ.filtered(lambda a: a.state in ('provisional', 'contacting')))
        arrived = occ.filtered(lambda a: a.actual_arrival_at or a.state in ('done', 'installation_created', 'inspection_completed'))
        with_order = arrived.filtered(lambda a: a.installation_order_id)

        # Cars waiting for an installation order (any booking date).
        waiting_all = Appt.search([
            ('branch_id', 'in', sel_ids), ('state', '=', 'done'), ('is_check_only', '=', False),
            ('installation_order_id', '=', False), ('actual_arrival_at', '!=', False)],
            order='actual_arrival_at asc')
        waiting = []
        for appt in waiting_all:
            minutes = int((now_utc - fields.Datetime.to_datetime(appt.actual_arrival_at)).total_seconds() // 60)
            if minutes >= (appt.branch_id.arrival_order_alert_minutes or 30):
                waiting.append((appt, minutes))

        deliveries_today, late_orders = [], []
        if Order is not None and 'delivery_date' in Order._fields:
            custom_ids = selected.mapped('branch_id').ids
            deliveries_today = Order.search([('branch_id', 'in', custom_ids), ('delivery_date', '=', today_s),
                                             ('state', 'not in', ['cancel_order', 'draft'])])
            late_candidates = Order.search([('branch_id', 'in', custom_ids), ('delivery_date', '<', today_s),
                                            ('state', 'in', ACTIVE_ORDER_STATES)], order='delivery_date asc')
            late_orders = late_candidates.filtered(
                lambda o: not (o.create_invoice_id and o.create_invoice_id.state == 'posted')
                if 'create_invoice_id' in Order._fields else True)

        longest = waiting[-1][1] if waiting else 0
        if waiting:
            longest = max(m for _a, m in waiting)
        kpis = [
            {'key': 'booked', 'label': 'حجوزات اليوم', 'value': booked, 'unit': '/ %s سعة' % capacity,
             'pct': min(100, _pct(booked, capacity)),
             'note': ('يتبقى %s أماكن' % max(0, capacity - booked) if capacity > booked else 'اكتملت السعة') + (' · %s مبدئي' % provisional if provisional else ''),
             'tone': 'blue'},
            {'key': 'arrived', 'label': 'وصلت السيارات', 'value': len(arrived), 'unit': 'من %s' % booked,
             'pct': _pct(len(arrived), booked),
             'note': 'منها %s أُنشئ لها أمر تركيب' % len(with_order), 'tone': 'purple'},
            {'key': 'waiting', 'label': 'بانتظار أمر تركيب', 'value': len(waiting), 'unit': 'سيارة',
             'pct': 100 if waiting else 0,
             'note': ('أطول انتظار %s' % self._wait_text(longest)) if waiting else 'لا توجد سيارات منتظرة',
             'tone': 'alert' if waiting else 'neutral'},
            {'key': 'delivery', 'label': 'تسليم اليوم', 'value': len(deliveries_today), 'unit': 'سيارات',
             'pct': _pct(len(late_orders), len(deliveries_today) + len(late_orders)) if late_orders else 0,
             'note': ('%s متأخرة عن موعدها' % len(late_orders)) if late_orders else 'لا توجد تسليمات متأخرة',
             'tone': 'green'},
        ]

        # Timeline only for a single branch (slots differ between branches).
        timeline, timeline_note = [], ''
        if len(selected) == 1:
            timeline = self._timeline(selected, occupying[selected.id] | no_show_today, today, local_now, booked, capacity)
        else:
            timeline_note = _('اختر فرعًا واحدًا لعرض خط سير اليوم حسب فترات الاستقبال.')

        alerts = self._today_alerts(selected, occ, waiting, late_orders, now_utc, local_now)

        stage_counts = {}
        for appt in occ | no_show_today:
            key = self._stage_key(appt)
            stage_counts[key] = stage_counts.get(key, 0) + 1
        states = [{'key': k, 'label': STAGE_LABELS[k], 'count': stage_counts[k]}
                  for k in ('provisional', 'confirmed', 'done', 'waiting', 'order', 'noshow') if stage_counts.get(k)]

        branches = []
        for cfg in all_cfg:
            count, cap = len(occupying[cfg.id]), cfg.capacity or 0
            pct = _pct(count, cap)
            branches.append({'id': cfg.id, 'name': cfg.branch_id.display_name, 'count': count, 'cap': cap,
                             'pct': min(100, pct), 'level': 'full' if pct >= 85 else 'mid' if pct >= 50 else 'low',
                             'selected': cfg in selected and len(selected) == 1})
        branches.sort(key=lambda b: -b['pct'])

        end_today = self._utc_bound(today + timedelta(days=1))
        end_week = self._utc_bound(today + timedelta(days=7))
        fu_domain = [('branch_id', 'in', sel_ids), ('state', 'in', FOLLOWUP_STATES)]
        fu_overdue = Appt.search(fu_domain + [('next_contact_at', '<', now_utc)])
        fu_today = Appt.search(fu_domain + [('next_contact_at', '>=', now_utc), ('next_contact_at', '<', end_today)])
        fu_week = Appt.search(fu_domain + [('next_contact_at', '>=', now_utc), ('next_contact_at', '<', end_week)])
        expiring = Appt.search([('branch_id', 'in', sel_ids), ('state', 'in', ['provisional', 'contacting']),
                                ('hold_until', '>', now_utc), ('hold_until', '<=', now_utc + timedelta(hours=1))])
        followups = [
            {'key': 'overdue', 'label': 'متأخرة', 'count': len(fu_overdue), 'ids': fu_overdue.ids, 'tone': 'alert'},
            {'key': 'today', 'label': 'اليوم', 'count': len(fu_today), 'ids': fu_today.ids, 'tone': 'blue'},
            {'key': 'week', 'label': 'خلال 7 أيام', 'count': len(fu_week), 'ids': fu_week.ids, 'tone': 'neutral'},
        ]
        return {'kpis': kpis, 'timeline': timeline, 'timeline_note': timeline_note, 'alerts': alerts,
                'alerts_count': len(alerts), 'states': states, 'states_total': sum(s['count'] for s in states),
                'branch_occupancy': branches, 'followups': followups,
                'expiring': {'count': len(expiring), 'ids': expiring.ids}}

    @staticmethod
    def _wait_text(minutes):
        if minutes >= 1440:
            return '%s يوم %s' % (minutes // 1440, _fmt_hours((minutes % 1440) / 60.0))
        if minutes >= 60:
            return '%s ساعة %s دقيقة' % (minutes // 60, minutes % 60)
        return '%s دقيقة' % minutes

    def _timeline(self, cfg, appts, today, local_now, booked, capacity):
        today_s = fields.Date.to_string(today)
        now_hour = local_now.hour + local_now.minute / 60.0
        exceptions = self.env['ycc.exception'].search([
            ('branch_id', '=', cfg.id), ('date', '<=', today_s),
            '|', '&', ('end_date', '=', False), ('date', '=', today_s), ('end_date', '>=', today_s)])
        closed_day = bool(exceptions.filtered(lambda e: not e.slot_id))
        closed_slots = set(exceptions.mapped('slot_id').ids)
        by_slot = {}
        for appt in appts:
            for day, slot in self._safe_periods(appt):
                if day == today_s:
                    by_slot.setdefault(slot.id, []).append(appt)
        rows = []
        remaining = max(0, capacity - booked)
        slots = self.env['ycc.slot'].search([('branch_id', '=', cfg.id), ('active', '=', True)], order='start_hour')
        for slot in slots.filtered(lambda s: s.operates_on(today)):
            closed = closed_day or slot.id in closed_slots
            if closed:
                status, caption = 'closed', 'مغلقة'
            elif now_hour >= slot.end_hour:
                status, caption = 'past', 'انتهت'
            elif now_hour >= slot.start_hour:
                status, caption = 'now', 'الآن'
            else:
                status, caption = 'next', 'قادمة'
            cars = []
            seen = set()
            for appt in by_slot.get(slot.id, []):
                if appt.id in seen:
                    continue
                seen.add(appt.id)
                key = self._stage_key(appt)
                cars.append({'id': appt.id, 'name': appt.partner_id.name or appt.name, 'stage': key,
                             'label': STAGE_LABELS[key], 'ref': appt.name,
                             'vehicle': appt.car_type_id.display_name or appt.vehicle_model or ''})
            rows.append({'id': slot.id, 'time': slot.name, 'caption': caption, 'status': status, 'cars': cars,
                         'free': status in ('next', 'now') and remaining > 0,
                         'free_text': '+ متاح · %s أماكن متبقية اليوم' % remaining})
        return rows

    def _today_alerts(self, selected, occ, waiting, late_orders, now_utc, local_now):
        alerts = []
        for appt, minutes in sorted(waiting, key=lambda x: -x[1]):
            local_arrival = self._local(appt.actual_arrival_at)
            alerts.append({'severity': 1, 'tone': 'alert', 'tag': '%sد' % minutes if minutes < 1440 else '%sي' % (minutes // 1440),
                           'title': '%s — بانتظار أمر تركيب' % (appt.partner_id.name or appt.name),
                           'meta': 'وصلت %s · %s · أنشأ الحجز: %s' % (local_arrival.strftime('%H:%M') if local_arrival else '-', appt.name, appt.create_uid.name or '-'),
                           'action': 'فتح الحجز', 'model': 'ycc.appointment', 'res_id': appt.id})
        today = local_now.date()
        for order in late_orders[:8]:
            days = (today - fields.Date.to_date(order.delivery_date)).days
            alerts.append({'severity': 2, 'tone': 'warn', 'tag': '%sي' % days,
                           'title': 'تأخر تسليم %s' % order.display_name,
                           'meta': 'موعده %s · %s' % (fields.Date.to_string(order.delivery_date), order.partner_id.name or ''),
                           'action': 'فتح الأمر', 'model': 'wo.installation.order.mst', 'res_id': order.id})
        now_hour = local_now.hour + local_now.minute / 60.0
        today_s = fields.Date.to_string(today)
        for appt in occ.filtered(lambda a: a.state == 'confirmed' and a.slot_id and fields.Date.to_string(a.date) == today_s):
            delay = int((now_hour - appt.slot_id.start_hour) * 60)
            if delay >= 60:
                alerts.append({'severity': 3, 'tone': 'neutral', 'tag': '%sد' % delay,
                               'title': '%s لم يصل بعد' % (appt.partner_id.name or appt.name),
                               'meta': 'موعده %s · %s' % (appt.slot_id.name, appt.phone or ''),
                               'action': 'فتح الحجز', 'model': 'ycc.appointment', 'res_id': appt.id})
        alerts.sort(key=lambda a: a['severity'])
        return alerts

    # -------------------------------------------------------------- tab: journey
    def _in_period(self, selected, start, end):
        """Bookings whose booking start date falls in [start, end) — the calendar's basis."""
        return self.env['ycc.appointment'].search([
            ('branch_id', 'in', selected.ids),
            ('date', '>=', fields.Date.to_string(start)), ('date', '<', fields.Date.to_string(end))])

    def _avg_wait(self, recs):
        waits = [max(0.0, (fields.Datetime.to_datetime(a.installation_order_id.create_date)
                           - fields.Datetime.to_datetime(a.actual_arrival_at)).total_seconds() / 60.0)
                 for a in recs if a.installation_order_id and a.actual_arrival_at]
        return _avg(waits)

    def _journey_data(self, selected, start, end, now_utc, cmp_period=None):
        created = self._in_period(selected, start, end)
        previous = self._in_period(selected, cmp_period[0], cmp_period[1]) if cmp_period else None
        total = len(created)

        def reached(recs):
            confirmed = recs.filtered(lambda a: a.state in REACHED_CONFIRMED or a.installation_order_id)
            arrived = recs.filtered(lambda a: a.actual_arrival_at or a.installation_order_id)
            ordered = recs.filtered(lambda a: a.installation_order_id)
            completed = ordered.filtered(lambda a: a.service_stage in ('completed', 'invoice_closed'))
            closed = ordered.filtered(lambda a: a.service_stage == 'invoice_closed')
            return [recs, confirmed, arrived, ordered, completed, closed]

        steps = reached(created)
        prev_steps = reached(previous) if previous is not None else None
        labels = ['حجز مبدئي', 'مؤكد', 'وصلت', 'أمر تركيب', 'تم الإنجاز', 'إقفال الفاتورة']
        funnel = []
        for i, recs in enumerate(steps):
            count = len(recs)
            rate = None if i == 0 else _pct(count, len(steps[i - 1]))
            prev_count = len(prev_steps[i]) if prev_steps else None
            funnel.append({'key': 'step%s' % i, 'label': labels[i], 'value': count,
                           'delta': _delta(count, prev_count),
                           'h': max(4, _pct(count, total)) if total else 4,
                           'rate': 'البداية' if i == 0 else '%s%% من السابقة' % rate,
                           'weak': i > 0 and rate is not None and rate < 75, 'ids': recs.ids})
        overall = _pct(len(steps[-1]), total)

        def leak_counts(recs):
            return {
                'expired': recs.filtered(lambda a: a.state == 'expired'),
                'cancelled': recs.filtered(lambda a: a.state == 'cancelled'),
                'no_show': recs.filtered(lambda a: a.state == 'no_show'),
                'postponed': recs.filtered(lambda a: a.was_postponed),
            }
        now_leaks = leak_counts(created)
        prev_leaks = leak_counts(previous) if previous is not None else None

        def bars(groups):
            biggest = max([len(v) for _k, v in groups] or [0])
            return [{'label': k, 'count': len(v), 'pct': _pct(len(v), biggest)} for k, v in groups if len(v)]

        expired = now_leaks['expired']
        no_contact = expired.filtered(lambda a: not a.contact_ids)
        no_answer = (expired - no_contact).filtered(lambda a: a.contact_ids.sorted('contact_at')[-1:].result == 'no_answer')
        expired_reasons = bars([('لم يتم التواصل', no_contact), ('لم يرد العميل', no_answer),
                                ('أخرى', expired - no_contact - no_answer)])

        def by_code(recs, options):
            groups = [(label, recs.filtered(lambda a, c=code: a.close_reason_code == c)) for code, label in options]
            groups.append(('غير مصنف (قديم)', recs.filtered(lambda a: not a.close_reason_code)))
            groups.sort(key=lambda g: -len(g[1]))
            return bars(groups)

        postponed = now_leaks['postponed']
        postponed_avg = _avg([a.postponement_count for a in postponed])
        leak_defs = [
            ('expired', 'انتهت المهلة دون تأكيد', '%s%% من الحجوزات' % _pct(len(expired), total), expired_reasons, 'amber'),
            ('cancelled', 'ملغي', '%s%% من الحجوزات' % _pct(len(now_leaks['cancelled']), total),
             by_code(now_leaks['cancelled'], CANCEL_REASONS), 'red'),
            ('no_show', 'لم يحضر', '%s%% من المؤكد' % _pct(len(now_leaks['no_show']), len(steps[1])),
             by_code(now_leaks['no_show'], NO_SHOW_REASONS), 'gray'),
            ('postponed', 'تم تأجيله', 'متوسط %.1f مرة' % postponed_avg if postponed_avg else '—',
             bars([('مرة واحدة', postponed.filtered(lambda a: a.postponement_count == 1)),
                   ('مرتين', postponed.filtered(lambda a: a.postponement_count == 2)),
                   ('3 مرات فأكثر', postponed.filtered(lambda a: a.postponement_count >= 3))]), 'orange'),
        ]
        leaks = []
        for key, title, share, reasons, tone in leak_defs:
            leaks.append({'key': key, 'title': title, 'value': len(now_leaks[key]), 'share': share,
                          'reasons': reasons, 'tone': tone, 'ids': now_leaks[key].ids,
                          'delta': _delta(len(now_leaks[key]), len(prev_leaks[key]) if prev_leaks else None, better='down')})

        def headline(recs, stp):
            n = len(recs)
            return {
                'total': n, 'conv': _pct(len(stp[1]), n) if n else None, 'arrived': len(stp[2]),
                'orders': len(stp[3]), 'closed_rate': _pct(len(stp[5]), n) if n else None,
                'cancelled': len(recs.filtered(lambda a: a.state == 'cancelled')),
                'no_show': len(recs.filtered(lambda a: a.state == 'no_show')),
                'wait': self._avg_wait(recs),
            }
        cur = headline(created, steps)
        prv = headline(previous, prev_steps) if previous is not None else {}
        summary_defs = [
            ('total', 'إجمالي الحجوزات', '%s', 'up', False, 'blue', steps[0].ids),
            ('conv', 'نسبة التأكيد', '%s%%', 'up', True, 'purple', steps[1].ids),
            ('arrived', 'وصلت السيارات', '%s', 'up', False, 'purple', steps[2].ids),
            ('orders', 'أوامر التركيب', '%s', 'up', False, 'green', steps[3].ids),
            ('closed_rate', 'نسبة إقفال الفاتورة', '%s%%', 'up', True, 'green', steps[5].ids),
            ('cancelled', 'ملغي', '%s', 'down', False, 'red', now_leaks['cancelled'].ids),
            ('no_show', 'لم يحضر', '%s', 'down', False, 'gray', now_leaks['no_show'].ids),
            ('wait', 'الوصول ← أمر التركيب', '%s د', 'down', False, 'amber', []),
        ]
        summary = []
        for key, title, fmt, better, points, tone, ids in summary_defs:
            value = cur.get(key)
            prev_value = prv.get(key) if prv else None
            if key == 'wait':
                value = int(round(value)) if value is not None else None
                prev_value = int(round(prev_value)) if prev_value is not None else None
            summary.append({'key': key, 'title': title, 'tone': tone, 'ids': ids,
                            'value': (fmt % value) if value is not None else '—',
                            'prev': (fmt % prev_value) if prev_value is not None else '—',
                            'delta': _delta(value, prev_value, better=better, unit=' د' if key == 'wait' else '', points=points)})

        return {'summary': summary, 'funnel': funnel, 'funnel_overall': overall, 'funnel_total': total, 'leaks': leaks,
                'durations': self._durations(created, selected, start, end),
                'delivery_changes': self._delivery_changes(selected, start, end),
                'heatmap': self._heatmap(selected, start, end) if len(selected) == 1 else None,
                'heatmap_note': '' if len(selected) == 1 else _('اختر فرعًا واحدًا لعرض خريطة الازدحام حسب الفترات.')}

    def _durations(self, created, selected, start, end):
        Appt = self.env['ycc.appointment']
        Order = self._orders_model()
        rows = []
        to_arrival = [(fields.Datetime.to_datetime(a.actual_arrival_at) - fields.Datetime.to_datetime(a.create_date)).total_seconds() / 86400.0
                      for a in created if a.actual_arrival_at]
        avg_arrival = _avg(to_arrival)
        rows.append({'key': 'booking_arrival', 'from': 'من الحجز إلى الوصول',
                     'value': ('%.1f' % avg_arrival) if avg_arrival is not None else '—', 'unit': 'يوم',
                     'status': 'من %s حجز وصلت' % len(to_arrival), 'tone': 'neutral'})
        linked = created.filtered(lambda a: a.installation_order_id and a.actual_arrival_at)
        waits = [max(0.0, (fields.Datetime.to_datetime(a.installation_order_id.create_date) - fields.Datetime.to_datetime(a.actual_arrival_at)).total_seconds() / 60.0)
                 for a in linked]
        avg_wait = _avg(waits)
        target = int(round(_avg(selected.mapped('arrival_order_alert_minutes')) or 30))
        rows.append({'key': 'arrival_order', 'from': 'من الوصول إلى أمر التركيب',
                     'value': ('%d' % avg_wait) if avg_wait is not None else '—', 'unit': 'دقيقة',
                     'status': ('ضمن الهدف (%s دقيقة)' % target) if avg_wait is not None and avg_wait <= target
                     else ('أعلى من الهدف (%s دقيقة)' % target) if avg_wait is not None else 'لا توجد بيانات',
                     'tone': 'good' if avg_wait is not None and avg_wait <= target else 'bad' if avg_wait is not None else 'neutral'})
        on_time = None
        if Order is not None:
            orders = linked.mapped('installation_order_id')
            done_field = 'compelete_done_date' if 'compelete_done_date' in Order._fields else None
            if done_field:
                spans, punctual, measured = [], 0, 0
                for order in orders:
                    done = order[done_field]
                    if not done:
                        continue
                    done_dt = fields.Datetime.to_datetime(done) if Order._fields[done_field].type == 'datetime' else datetime.combine(fields.Date.to_date(done), dtime.min)
                    spans.append((done_dt - fields.Datetime.to_datetime(order.create_date)).total_seconds() / 86400.0)
                    if order.delivery_date:
                        measured += 1
                        if done_dt.date() <= fields.Date.to_date(order.delivery_date):
                            punctual += 1
                avg_span = _avg(spans)
                rows.append({'key': 'order_done', 'from': 'من أمر التركيب إلى الإنجاز',
                             'value': ('%.1f' % avg_span) if avg_span is not None else '—', 'unit': 'يوم',
                             'status': 'من %s أمر منجز' % len(spans), 'tone': 'neutral'})
                if measured:
                    on_time = {'pct': _pct(punctual, measured), 'text': '%s أمر أُنجز في موعد التسليم أو قبله من أصل %s' % (punctual, measured)}
            if on_time is None and orders:
                changed = self.env['ycc.delivery.change'].search([('installation_order_id', 'in', orders.ids)]).mapped('installation_order_id')
                kept = len(orders - changed)
                on_time = {'pct': _pct(kept, len(orders)), 'text': '%s أمر بدون تغيير موعد التسليم من أصل %s' % (kept, len(orders))}
        return {'rows': rows, 'on_time': on_time}

    def _delivery_changes(self, selected, start, end):
        changes = self.env['ycc.delivery.change'].search([
            ('appointment_id.branch_id', 'in', selected.ids),
            ('change_date', '>=', self._utc_bound(start)), ('change_date', '<', self._utc_bound(end))])
        customer = changes.filtered(lambda c: c.reason_code == 'customer_delay')
        branch = changes.filtered(lambda c: c.reason_code == 'branch_postponement')
        legacy = changes - customer - branch
        total = len(customer) + len(branch)
        top = ''
        if branch:
            counts = {}
            for change in branch:
                name = change.appointment_id.branch_id.branch_id.display_name
                counts[name] = counts.get(name, 0) + 1
            name, count = max(counts.items(), key=lambda kv: kv[1])
            top = '%s (%s من %s)' % (name, count, len(branch))
        return {'total': len(changes), 'customer': len(customer), 'branch': len(branch), 'legacy': len(legacy),
                'customer_pct': _pct(len(customer), total), 'branch_pct': _pct(len(branch), total),
                'top_branch': top, 'customer_ids': customer.mapped('appointment_id').ids,
                'branch_ids': branch.mapped('appointment_id').ids}

    def _heatmap(self, cfg, start, end):
        Appt = self.env['ycc.appointment']
        start_s, end_s = fields.Date.to_string(start), fields.Date.to_string(end)
        appts = Appt.search([
            ('branch_id', '=', cfg.id), ('date', '<', end_s),
            '|', '&', ('end_date', '=', False), ('date', '>=', start_s), ('end_date', '>=', start_s),
            ('state', 'in', ['confirmed', 'done', 'installation_created', 'postponed', 'inspection_completed'])])
        counts = {}
        for appt in appts:
            for day, slot in self._safe_periods(appt):
                counts[(day, slot.id)] = counts.get((day, slot.id), 0) + 1
        slots = self.env['ycc.slot'].search([('branch_id', '=', cfg.id), ('active', '=', True)], order='start_hour')
        capacity = cfg.capacity or 1
        acc = {}
        current = start
        while current < end:
            day_s = fields.Date.to_string(current)
            for slot in slots:
                if slot.operates_on(current):
                    value = min(100, _pct(counts.get((day_s, slot.id), 0), capacity))
                    acc.setdefault((current.weekday(), slot.id), []).append(value)
            current += timedelta(days=1)
        rows = []
        for weekday, label in WEEKDAYS_SAT_FIRST:
            cells = []
            for slot in slots:
                values = acc.get((weekday, slot.id))
                if values is None:
                    cells.append({'v': None, 'text': '—', 'level': 'off'})
                    continue
                v = int(round(_avg(values)))
                level = 'l5' if v >= 90 else 'l4' if v >= 70 else 'l3' if v >= 50 else 'l2' if v >= 30 else 'l1'
                cells.append({'v': v, 'text': '%s%%' % v, 'level': level})
            rows.append({'day': label, 'cells': cells})
        return {'cols': [s.name for s in slots], 'rows': rows}

    # ----------------------------------------------------------------- tab: team
    def _team_data(self, selected, start, end, now_utc, cmp_period=None):
        Appt = self.env['ycc.appointment']
        created = self._in_period(selected, start, end)
        previous = self._in_period(selected, cmp_period[0], cmp_period[1]) if cmp_period else None
        contacts = self.env['ycc.contact'].search([
            ('appointment_id.branch_id', 'in', selected.ids),
            ('contact_at', '>=', self._utc_bound(start)), ('contact_at', '<', self._utc_bound(end))])
        overdue = Appt.search([('branch_id', 'in', selected.ids), ('state', 'in', FOLLOWUP_STATES),
                               ('next_contact_at', '<', now_utc)])
        linked = created.filtered(lambda a: a.installation_order_id and a.actual_arrival_at)
        users = created.mapped('create_uid') | contacts.mapped('user_id') | overdue.mapped('create_uid') \
            | linked.mapped('installation_order_id.create_uid')
        manager = self.env.ref('yousentech_car_appointments.group_ycc_manager', raise_if_not_found=False)
        booking = self.env.ref('yousentech_car_appointments.group_ycc_booking', raise_if_not_found=False)
        arrival = self.env.ref('yousentech_car_appointments.group_ycc_sales_arrival', raise_if_not_found=False)
        rows = []
        for user in users:
            mine = created.filtered(lambda a: a.create_uid == user)
            confirmed = mine.filtered(lambda a: a.state in REACHED_CONFIRMED or a.installation_order_id)
            waits = [max(0.0, (fields.Datetime.to_datetime(a.installation_order_id.create_date) - fields.Datetime.to_datetime(a.actual_arrival_at)).total_seconds() / 60.0)
                     for a in linked if a.installation_order_id.create_uid == user]
            avg_wait = _avg(waits)
            if manager and manager in user.groups_id:
                role, role_key = 'مدير المواعيد', 'manager'
            elif booking and booking in user.groups_id:
                role, role_key = 'موظف حجوزات', 'booking'
            elif arrival and arrival in user.groups_id:
                role, role_key = 'مندوب وصول', 'arrival'
            else:
                role, role_key = 'مستخدم', 'other'
            mine_overdue = overdue.filtered(lambda a: a.create_uid == user)
            prev_conv = prev_created = None
            if previous is not None:
                before = previous.filtered(lambda a: a.create_uid == user)
                prev_created = len(before)
                prev_ok = before.filtered(lambda a: a.state in REACHED_CONFIRMED or a.installation_order_id)
                prev_conv = _pct(len(prev_ok), len(before)) if before else None
            rows.append({
                'id': user.id, 'name': user.name, 'initials': (user.name or '?').strip()[:1],
                'role': role, 'role_key': role_key,
                'created': len(mine), 'created_ids': mine.ids,
                'conv': _pct(len(confirmed), len(mine)) if mine else None,
                'expired': len(mine.filtered(lambda a: a.state == 'expired')),
                'cancelled': len(mine.filtered(lambda a: a.state == 'cancelled')),
                'no_show': len(mine.filtered(lambda a: a.state == 'no_show')),
                'contacts': len(contacts.filtered(lambda c: c.user_id == user)),
                'late': len(mine_overdue), 'late_ids': mine_overdue.ids,
                'orders': len(waits), 'wait': int(round(avg_wait)) if avg_wait is not None else None,
                'created_delta': _delta(len(mine), prev_created),
                'conv_delta': _delta(_pct(len(confirmed), len(mine)) if mine else None, prev_conv, points=True),
            })
        rows.sort(key=lambda r: (r['conv'] is None, -(r['conv'] or 0), -r['created']))
        for index, row in enumerate(rows):
            row['avatar'] = 'a%s' % (index % 6)
            row['conv_level'] = None if row['conv'] is None else 'high' if row['conv'] >= 80 else 'mid' if row['conv'] >= 65 else 'low'
            row['late_level'] = 'ok' if not row['late'] else 'high' if row['late'] >= 3 else 'mid'
            row['wait_text'] = '%s د' % row['wait'] if row['wait'] is not None else '—'
            row['wait_bad'] = row['wait'] is not None and row['wait'] > 30
            row['conv_text'] = '%s%%' % row['conv'] if row['conv'] is not None else '—'

        spotlights = []
        ranked = [r for r in rows if r['conv'] is not None and r['created'] >= 5] or [r for r in rows if r['conv'] is not None]
        if ranked:
            best = max(ranked, key=lambda r: (r['conv'], r['created']))
            confirmed_count = int(round(best['conv'] * best['created'] / 100.0))
            spotlights.append({'kind': 'best', 'kicker': 'الأعلى تحويلًا', 'name': best['name'], 'initials': best['initials'],
                               'detail': '%s حجز مؤكد من %s' % (confirmed_count, best['created']), 'metric': best['conv_text']})
        fast = [r for r in rows if r['wait'] is not None and r['orders'] >= 3] or [r for r in rows if r['wait'] is not None]
        if fast:
            quick = min(fast, key=lambda r: r['wait'])
            spotlights.append({'kind': 'fast', 'kicker': 'الأسرع في إنشاء أمر التركيب', 'name': quick['name'], 'initials': quick['initials'],
                               'detail': 'متوسط بعد وصول السيارة · %s أمر' % quick['orders'], 'metric': quick['wait_text']})
        needy = [r for r in rows if r['late'] or r['expired']]
        if needy:
            worst = max(needy, key=lambda r: (r['late'] * 2 + r['expired']))
            spotlights.append({'kind': 'attention', 'kicker': 'يحتاج متابعة', 'name': worst['name'], 'initials': worst['initials'],
                               'detail': '%s متابعات متأخرة · %s انتهت مهلتها' % (worst['late'], worst['expired']), 'metric': worst['conv_text']})

        channel_labels = dict(self.env['ycc.contact']._fields['channel'].selection)
        result_labels = dict(self.env['ycc.contact']._fields['result'].selection)

        def distribution(field, labels):
            counts = {}
            for contact in contacts:
                counts[contact[field]] = counts.get(contact[field], 0) + 1
            biggest = max(counts.values() or [0])
            return [{'key': k, 'label': labels.get(k, k), 'count': v, 'pct': _pct(v, biggest)}
                    for k, v in sorted(counts.items(), key=lambda kv: -kv[1])]

        hours = {h: 0 for h in range(8, 21)}
        for contact in contacts:
            local = self._local(contact.contact_at)
            if local and local.hour in hours:
                hours[local.hour] += 1
        peak = max(hours.values() or [0])
        hour_bars = [{'hour': h, 'v': _pct(c, peak) if peak else 0, 'count': c, 'peak': bool(peak) and c == peak} for h, c in hours.items()]
        peak_hour = max(hours, key=lambda h: hours[h]) if peak else None
        evening = len(created.filtered(lambda a: self._local(a.create_date).hour >= 18))
        return {'people': rows, 'spotlights': spotlights, 'compare_on': previous is not None,
                'channels': distribution('channel', channel_labels),
                'results': distribution('result', result_labels),
                'hours': hour_bars, 'contacts_total': len(contacts),
                'peak_text': ('ذروة التواصل الساعة %s:00' % peak_hour) if peak_hour is not None else 'لا يوجد تواصل مسجل في الفترة',
                'evening_pct': _pct(evening, len(created))}
