# -*- coding: utf-8 -*-
from datetime import date, timedelta
from odoo import http, fields
from odoo.http import request

class YCCCalendar(http.Controller):
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
        configurations = Branch.search([('active', '=', True)])
        branches = [
            {'id': config.id, 'name': config.branch_id.display_name,
             'custom_branch_id': config.branch_id.id}
            for config in configurations if config.branch_id
        ]
        if not branches: return {'branches':[],'slots':[],'appointments':[],'exceptions':[]}
        branch = Branch.browse(int(branch_id)) if branch_id else configurations.filtered(lambda c: c.branch_id)[:1]
        branch.check_access_rights('read')
        branch.check_access_rule('read')
        if not branch.exists() or not branch.branch_id: return {'branches':branches,'slots':[],'appointments':[],'exceptions':[]}
        first = fields.Date.from_string(start) if start else date.today()
        last = fields.Date.from_string(end) if end else first+timedelta(days=7)
        if last <= first or (last-first).days > 42: return {'error':'Invalid date range'}
        slots = request.env['ycc.slot'].search([('branch_id','=',branch.id),('active','=',True)])
        exceptions = request.env['ycc.exception'].search([('branch_id','=',branch.id),('date','>=',first),('date','<',last)])
        appointments = request.env['ycc.appointment'].search([('branch_id','=',branch.id),('date','<',last),'|','&',('end_date','=',False),('date','>=',first),('end_date','>=',first),('state','in',['provisional','contacting','confirmed','done','installation_created'])])
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
                    for covered_day, _slot in booking._covered_periods():
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
        now = fields.Datetime.now()
        return {'branches':branches,'branch_id':branch.id,'daily_capacity':branch.capacity,'arrival_only':request.env['ycc.appointment']._ycc_arrival_only_user(),'can_create':request.env['ycc.appointment']._ycc_can_book(),'lang':request.env.user.lang or 'en_US','today':fields.Date.to_string(fields.Date.context_today(request.env.user)), 'installation_by_day':installation_by_day,
            'slots':[{'id':s.id,'name':s.name,'start_hour':s.start_hour,'end_hour':s.end_hour,'capacity':branch.capacity,'days':[int(x) for x in s.weekday_ids.mapped('code')]} for s in slots],
            'exceptions':[{'date':fields.Date.to_string(e.date),'slot_id':e.slot_id.id or False,'reason':e.reason} for e in exceptions],
            'appointments':[{'id':a.id,'name':a.name,'date':fields.Date.to_string(a.date),'end_date':fields.Date.to_string(a.end_date or a.date),'slot_id':a.slot_id.id,'slot_ids':a._covered_slots().ids if a.slot_id and a.date else [],'periods':[{'date':d,'slot_id':slot.id} for d,slot in a._covered_periods() if first <= fields.Date.from_string(d) < last] if a.slot_id and a.date else [],'client':a.partner_id.name,'vehicle':'%s · %s'%((a.car_type_id.display_name or a.vehicle_model or ''),a.vehicle_plate or ''),'service':a.service_id.name or '','state':a.state,'installation_order_id':a.installation_order_id.id or False,'agent':a.agent_id.name or '','hold_until':a.hold_until or ''} for a in appointments if a._occupies(now)]}
