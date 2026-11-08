# -*- coding: utf-8 -*-
from datetime import date, timedelta, datetime
from calendar import timegm
import time
import pytz
from odoo import http, fields
from odoo.http import request
from odoo.exceptions import ValidationError

class YCCCalendar(http.Controller):
    @staticmethod
    def _calendar_periods(appointment):
        """Keep historical bookings visible if old slot settings no longer match.

        Booking create/write validation remains strict in the appointment model.
        """
        if not appointment.slot_id or not appointment.date:
            return []
        try:
            return appointment._covered_periods()
        except ValidationError:
            # A pre-existing booking may have non-contiguous/disabled slots.
            # Do not make the whole calendar unavailable because of one record.
            return [(fields.Date.to_string(appointment.date), appointment.slot_id)]

    @staticmethod
    def _exception_domain(branch_ids, first, last):
        """Exceptions overlapping [first, last): single-day or multi-day."""
        return [('branch_id', 'in', branch_ids),
                ('date', '<', fields.Date.to_string(last)),
                '|', ('end_date', '>=', fields.Date.to_string(first)),
                '&', ('end_date', '=', False), ('date', '>=', fields.Date.to_string(first))]

    @staticmethod
    def _exception_days(exception, first, last):
        """Every displayed day covered by an exception (end date inclusive)."""
        begin = max(fields.Date.from_string(exception.date), first)
        finish = min(fields.Date.from_string(exception.end_date or exception.date), last - timedelta(days=1))
        days = []
        while begin <= finish:
            days.append(fields.Date.to_string(begin))
            begin += timedelta(days=1)
        return days

    @http.route('/ycc/calendar/installation_action', type='json', auth='user')
    def installation_action(self, appointment_id=None):
        appointment = request.env['ycc.appointment'].browse(int(appointment_id or 0)).exists()
        if not appointment:
            return {'error': 'الحجز غير موجود'}
        return appointment.action_open_installation_wizard()

    @http.route('/ycc/calendar/forecast', type='json', auth='user')
    def forecast(self, branch_id=None, date=None):
        return request.env['ycc.appointment'].forecast_delivery_load(branch_id, date)

    @http.route('/ycc/calendar/data',type='json',auth='user')
    def calendar_data(self,branch_id=None,start=None,end=None):
        Branch = request.env['ycc.branch']
        # Settings are stored in ycc.branch, while branch names and identities
        # come exclusively from the existing V3 custom.branches model.
        configurations = Branch.search([
            ('active', '=', True),
            ('branch_id', 'in', request.env.user.allowed_branch_ids.ids),
        ])
        branches = [
            {'id': config.id, 'name': config.branch_id.display_name,
             'custom_branch_id': config.branch_id.id}
            for config in configurations if config.branch_id
        ]
        if not branches: return {'branches':[],'slots':[],'appointments':[],'exceptions':[]}
        branch = configurations.filtered(lambda c: c.id == int(branch_id))[:1] if branch_id else configurations.filtered(lambda c: c.branch_id)[:1]
        if not branch or not branch.exists() or not branch.branch_id:
            return {'branches': branches, 'slots': [], 'appointments': [], 'exceptions': [], 'error': 'الفرع غير مسموح للمستخدم'}
        branch.check_access_rights('read')
        branch.check_access_rule('read')
        first = fields.Date.from_string(start) if start else date.today()
        last = fields.Date.from_string(end) if end else first+timedelta(days=7)
        if last <= first or (last-first).days > 42: return {'error':'Invalid date range'}
        slots = request.env['ycc.slot'].search([('branch_id','=',branch.id),('active','=',True)])
        exceptions = request.env['ycc.exception'].search(self._exception_domain([branch.id], first, last))
        appointments = request.env['ycc.appointment'].search([('branch_id','=',branch.id),('date','<',last),'|','&',('end_date','=',False),('date','>=',first),('end_date','>=',first),('state','in',['provisional','contacting','confirmed','done','installation_created','postponed','no_show','inspection_completed'])])
        # Customer-service warnings are calculated at request time, without
        # modifying the appointment or installation-order workflow.
        tz_name = request.env.user.tz or request.env.company.partner_id.tz or 'Asia/Riyadh'
        try:
            local_tz = pytz.timezone(tz_name)
        except pytz.UnknownTimeZoneError:
            local_tz = pytz.UTC
        local_now = datetime.now(local_tz)
        Appointment = request.env['ycc.appointment']

        def warning_data(booking):
            # V6.66: shared with the manager dashboard (one definition).
            return Appointment._ycc_warning_data(booking, local_now)
        # Active installation orders spanning the selected day (not appointments).
        # Order date and delivery date are inclusive; finished/cancelled orders
        # are excluded by the explicit active-state allowlist.
        # An installation order disappears as soon as an invoice is created,
        # regardless of whether the invoice is draft or posted.
        installation_by_day = {}
        Order = request.env['wo.installation.order.mst']
        required = ('order_date', 'delivery_date', 'state', 'branch_id', 'partner_id')
        if all(field in Order._fields for field in required):
            active_states = ['confirm', 'under_checking', 'work_order',
                             'execute_request', 'execute_started', 'return_to_modify']
            orders = Order.search([
                ('branch_id', '=', branch.branch_id.id),
                ('state', 'in', active_states),
                ('create_invoice_id', '=', False),
                ('order_date', '<', fields.Date.to_string(last)),
                ('delivery_date', '>=', fields.Date.to_string(first)),
            ], order='order_date asc, id asc')
            # Exclude a linked installation order ONLY on dates where its
            # appointment actually occupies a calendar slot.  The same order
            # remains visible on other days of its active date range.
            linked_appointments = request.env['ycc.appointment'].search([
                ('branch_id', '=', branch.id),
                ('installation_order_id', 'in', orders.ids),
                ('date', '<', fields.Date.to_string(last)),
                '|', '&', ('end_date', '=', False), ('date', '>=', fields.Date.to_string(first)),
                ('end_date', '>=', fields.Date.to_string(first)),
            ])
            excluded_order_days = set()
            for booking in linked_appointments:
                if booking.slot_id and booking.date and booking._occupies():
                    for covered_day, _slot in self._calendar_periods(booking):
                        if first <= fields.Date.from_string(covered_day) < last:
                            excluded_order_days.add((booking.installation_order_id.id, covered_day))
            for order in orders:
                begin = fields.Date.from_string(order.order_date)
                finish = fields.Date.from_string(order.delivery_date)
                current = max(begin, first)
                while current <= min(finish, last - timedelta(days=1)):
                    key = fields.Date.to_string(current)
                    if (order.id, key) in excluded_order_days:
                        current += timedelta(days=1)
                        continue
                    installation_by_day.setdefault(key, []).append({
                        'id': order.id,
                        'name': order.display_name,
                        'customer': order.partner_id.name or 'عميل غير محدد',
                        'order_date': fields.Date.to_string(order.order_date),
                        'delivery_date': fields.Date.to_string(order.delivery_date),
                        'delivery_period': (order.delivery_period.display_name
                                            if 'delivery_period' in Order._fields and order.delivery_period
                                            else 'غير محددة'),
                        'state': dict(Order._fields['state'].selection).get(order.state, order.state)
                                 if isinstance(Order._fields['state'].selection, (list, tuple)) else order.state,
                    })
                    current += timedelta(days=1)
        # Independent daily check-up capacity. Original appointment dates are never modified.
        check_by_day = {}
        if 'check_date' in Order._fields:
            check_orders = Order.search([
                ('branch_id', '=', branch.branch_id.id),
                ('check_date', '>=', fields.Date.to_string(first)),
                ('check_date', '<', fields.Date.to_string(last)),
            ], order='check_date asc, id asc')
            for order in check_orders:
                linked = order.ycc_appointment_id if 'ycc_appointment_id' in Order._fields else False
                if not linked:
                    linked = request.env['ycc.appointment'].search([('installation_order_id', '=', order.id)], limit=1)
                key = fields.Date.to_string(order.check_date)
                check_by_day.setdefault(key, []).append({
                    'id': order.id, 'name': order.display_name,
                    'customer': order.partner_id.name or '',
                    'vehicle': (linked.vehicle_plate or '') if linked else '',
                    'booking_name': linked.name if linked else '',
                    'booking_date': fields.Date.to_string(linked.date) if linked and linked.date else '',
                    'check_date': key,
                })
        # Cross-branch comparison: same day, same occupancy definition as the
        # calendar (one appointment per day, even for multi-slot bookings).
        # Read through the requesting user's normal ACLs / record rules.
        comparison = {}
        visible_configs = configurations.filtered(lambda c: c.branch_id)
        if len(visible_configs) > 1:
            peer_bookings = request.env['ycc.appointment'].search([
                ('branch_id', 'in', visible_configs.ids),
                ('date', '<', fields.Date.to_string(last)),
                '|', '&', ('end_date', '=', False), ('date', '>=', fields.Date.to_string(first)),
                ('end_date', '>=', fields.Date.to_string(first)),
                ('state', 'in', ['provisional', 'contacting', 'confirmed', 'done', 'installation_created','postponed','inspection_completed']),
            ])
            peer_counts = {}
            for appt in peer_bookings:
                if not appt.slot_id or not appt.date or not appt._occupies():
                    continue
                covered_dates = set()
                for covered_date, _slot in self._calendar_periods(appt):
                    if first <= fields.Date.from_string(covered_date) < last:
                        covered_dates.add(covered_date)
                for covered_date in covered_dates:
                    key = (appt.branch_id.id, covered_date)
                    peer_counts[key] = peer_counts.get(key, 0) + 1
            peer_slots = request.env['ycc.slot'].search([
                ('branch_id', 'in', visible_configs.ids), ('active', '=', True)])
            peer_exceptions = request.env['ycc.exception'].search(
                self._exception_domain(visible_configs.ids, first, last) + [('slot_id', '=', False)])
            blocked = {(ex.branch_id.id, ex_day) for ex in peer_exceptions
                       for ex_day in self._exception_days(ex, first, last)}
            for offset in range((last-first).days):
                current_day = first + timedelta(days=offset)
                date_key = fields.Date.to_string(current_day)
                items = []
                for config in visible_configs:
                    count = peer_counts.get((config.id, date_key), 0)
                    cap = config.capacity or 0
                    available_slots = peer_slots.filtered(lambda sl: sl.branch_id.id == config.id and (
                        not sl.weekday_ids or str(current_day.weekday()) in sl.weekday_ids.mapped('code')))
                    is_open = bool(cap > 0 and available_slots and (config.id, date_key) not in blocked)
                    items.append({'id': config.id, 'name': config.branch_id.display_name,
                                  'count': count, 'capacity': cap,
                                  'remaining': max(0, cap-count) if is_open else 0,
                                  'percent': min(100, round(count*100.0/cap)) if cap else 0,
                                  'open': is_open})
                items.sort(key=lambda x: (not x['open'], x['percent'] if x['open'] else 999,
                                          -x['remaining'], x['name']))
                comparison[date_key] = items
        # Customer-service indicators: shared model logic (V6.66) so the manager
        # dashboard shows exactly the same numbers for the same branch and range.
        service_items = Appointment._ycc_service_indicators(branch, first, last, local_now)
        # V6.64: cars that arrived but still have no installation order.
        # Sent with the arrival timestamp; the browser shows the card only
        # after the branch threshold and keeps the waiting timer ticking.
        arrival_alerts = []
        for waiting in Appointment.search([
                ('branch_id', '=', branch.id), ('state', '=', 'done'),
                ('is_check_only', '=', False), ('installation_order_id', '=', False),
                ('actual_arrival_at', '!=', False)], order='actual_arrival_at asc', limit=50):
            arrived_utc = fields.Datetime.from_string(waiting.actual_arrival_at)
            arrival_alerts.append({
                'id': waiting.id, 'name': waiting.name,
                'customer': waiting.partner_id.name or '',
                'vehicle': ' · '.join(x for x in (waiting.car_type_id.display_name or waiting.vehicle_model or '',
                                                   waiting.vehicle_plate or '') if x),
                'phone': waiting.phone or '',
                'agent': waiting.agent_id.name or '',
                'arrival_ts': timegm(arrived_utc.timetuple()) * 1000,
                'arrival_label': pytz.UTC.localize(arrived_utc).astimezone(local_tz).strftime('%Y-%m-%d %H:%M'),
            })
        now = fields.Datetime.now()
        return {'branches':branches,'arrival_alerts':arrival_alerts,'arrival_alert_minutes':branch.arrival_order_alert_minutes or 30,'server_now':int(time.time()*1000),'branch_id':branch.id,'daily_capacity':branch.capacity,'arrival_only':request.env['ycc.appointment']._ycc_arrival_only_user(),'can_create':request.env['ycc.appointment']._ycc_can_book(),'lang':request.env.user.lang or 'en_US','today':fields.Date.to_string(fields.Date.context_today(request.env.user)), 'installation_by_day':installation_by_day,'check_by_day':check_by_day,'check_capacity':branch.check_capacity,'branch_comparison':comparison,'service_indicators':service_items,
            'slots':[{'id':s.id,'name':s.name,'start_hour':s.start_hour,'end_hour':s.end_hour,'capacity':branch.capacity,'days':[int(x) for x in s.weekday_ids.mapped('code')]} for s in slots],
            'exceptions':[{'date':ex_day,'slot_id':e.slot_id.id or False,'reason':e.reason} for e in exceptions for ex_day in self._exception_days(e, first, last)],
            'appointments':[{'id':a.id,'name':a.name,'date':fields.Date.to_string(a.date),'end_date':fields.Date.to_string(a.end_date or a.date),'slot_id':a.slot_id.id,'slot_ids':list(dict.fromkeys(slot.id for _, slot in self._calendar_periods(a))) if a.slot_id and a.date else [],'periods':[{'date':d,'slot_id':slot.id} for d,slot in self._calendar_periods(a) if first <= fields.Date.from_string(d) < last] if a.slot_id and a.date else [],'client':a.partner_id.name,'vehicle':'%s · %s'%((a.car_type_id.display_name or a.vehicle_model or ''),a.vehicle_plate or ''),'service':a.service_id.name or '','state':a.state,'occupies':a._occupies(now),'service_stage':a.service_stage,'was_postponed':a.was_postponed,'installation_order_id':a.installation_order_id.id or False,'agent':a.agent_id.name or '','hold_until':a.hold_until or '', 'notes':a.notes or '', 'postponement_reason':a.last_postponement_reason or '', 'arrival_warning':warning_data(a)[0], 'delivery_warning':warning_data(a)[1], 'is_check_only':a.is_check_only, 'cancellation_reason':a.cancellation_reason or ''} for a in appointments if a._occupies(now) or a.state == 'no_show']}
