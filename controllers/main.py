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
        appointments = request.env['ycc.appointment'].search([('branch_id','=',branch.id),('date','<',last),'|','&',('end_date','=',False),('date','>=',first),('end_date','>=',first),('state','in',['provisional','contacting','confirmed','done'])])
        now = fields.Datetime.now()
        return {'branches':branches,'branch_id':branch.id,'arrival_only':request.env['ycc.appointment']._ycc_arrival_only_user(),'can_create':request.env['ycc.appointment']._ycc_can_book(),'lang':request.env.user.lang or 'en_US','today':fields.Date.to_string(fields.Date.context_today(request.env.user)),
            'slots':[{'id':s.id,'name':s.name,'start_hour':s.start_hour,'end_hour':s.end_hour,'capacity':branch.capacity,'days':[int(x) for x in s.weekday_ids.mapped('code')]} for s in slots],
            'exceptions':[{'date':fields.Date.to_string(e.date),'slot_id':e.slot_id.id or False,'reason':e.reason} for e in exceptions],
            'appointments':[{'id':a.id,'name':a.name,'date':fields.Date.to_string(a.date),'end_date':fields.Date.to_string(a.end_date or a.date),'slot_id':a.slot_id.id,'slot_ids':a._covered_slots().ids if a.slot_id and a.date else [],'periods':[{'date':d,'slot_id':slot.id} for d,slot in a._covered_periods() if first <= fields.Date.from_string(d) < last] if a.slot_id and a.date else [],'client':a.partner_id.name,'vehicle':'%s · %s'%((a.car_type_id.display_name or a.vehicle_model or ''),a.vehicle_plate or ''),'service':a.service_id.name or '','state':a.state,'agent':a.agent_id.name or '','hold_until':a.hold_until or ''} for a in appointments if a._occupies(now)]}
