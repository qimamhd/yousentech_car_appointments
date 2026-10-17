# -*- coding: utf-8 -*-
from datetime import date, timedelta
from odoo import http, fields
from odoo.http import request

class YCCCalendar(http.Controller):
    @http.route('/ycc/calendar/data',type='json',auth='user')
    def calendar_data(self,branch_id=None,start=None,end=None):
        Branch = request.env['ycc.branch']
        branches = Branch.search([]).read(['name'])
        if not branches: return {'branches':[],'slots':[],'appointments':[],'exceptions':[]}
        branch = Branch.browse(int(branch_id)) if branch_id else Branch.browse(branches[0]['id'])
        branch.check_access_rights('read')
        branch.check_access_rule('read')
        if not branch.exists(): return {'branches':branches,'slots':[],'appointments':[],'exceptions':[]}
        first = fields.Date.from_string(start) if start else date.today()
        last = fields.Date.from_string(end) if end else first+timedelta(days=7)
        if last <= first or (last-first).days > 42: return {'error':'Invalid date range'}
        slots = request.env['ycc.slot'].search([('branch_id','=',branch.id),('active','=',True)])
        exceptions = request.env['ycc.exception'].search([('branch_id','=',branch.id),('date','>=',first),('date','<',last)])
        appointments = request.env['ycc.appointment'].search([('branch_id','=',branch.id),('date','>=',first),('date','<',last),('state','in',['provisional','contacting','confirmed','done'])])
        now = fields.Datetime.now()
        return {'branches':branches,'branch_id':branch.id,'lang':request.env.user.lang or 'en_US','today':fields.Date.to_string(fields.Date.context_today(request.env.user)),
            'slots':[{'id':s.id,'name':s.name,'start_hour':s.start_hour,'end_hour':s.end_hour,'capacity':s.capacity,'days':[int(x) for x in s.weekday_ids.mapped('code')]} for s in slots],
            'exceptions':[{'date':fields.Date.to_string(e.date),'slot_id':e.slot_id.id or False,'reason':e.reason} for e in exceptions],
            'appointments':[{'id':a.id,'name':a.name,'date':fields.Date.to_string(a.date),'slot_id':a.slot_id.id,'slot_ids':a._covered_slots().ids,'client':a.partner_id.name,'vehicle':'%s · %s'%(a.vehicle_model,a.vehicle_plate),'service':a.service_id.name,'state':a.state,'agent':a.agent_id.name or '','hold_until':a.hold_until or ''} for a in appointments if a._occupies(now)]}
