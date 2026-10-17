# -*- coding: utf-8 -*-
from datetime import timedelta
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError

class YCCBranch(models.Model):
    _name = 'ycc.branch'
    _description = 'تهيئة مواعيد الفرع'
    name = fields.Char(string='الفرع', required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    provisional_minutes = fields.Integer(string='صلاحية الحجز المبدئي بالدقائق', default=120, required=True)
    slot_ids = fields.One2many('ycc.slot','branch_id',string='فترات الحجز')
    exception_ids = fields.One2many('ycc.exception','branch_id',string='الاستثناءات')

    @api.constrains('provisional_minutes')
    def _check_minutes(self):
        for rec in self:
            if rec.provisional_minutes <= 0:
                raise ValidationError(_('Hold duration must be positive.'))

class YCCWeekday(models.Model):
    _name = 'ycc.weekday'
    _description = 'أيام العمل'
    _order = 'code'
    name = fields.Char(required=True)
    code = fields.Selection([(str(i),str(i)) for i in range(7)],required=True)

class YCCSlot(models.Model):
    _name = 'ycc.slot'
    _description = 'فترات حجز السيارات'
    _order = 'branch_id, start_hour'
    branch_id = fields.Many2one('ycc.branch',required=True,ondelete='cascade')
    name = fields.Char(compute='_compute_name',store=True)
    start_hour = fields.Float(string='من الساعة',required=True)
    end_hour = fields.Float(string='إلى الساعة',required=True)
    capacity = fields.Integer(string='القدرة الاستيعابية',default=4,required=True)
    active = fields.Boolean(default=True)
    weekday_ids = fields.Many2many('ycc.weekday',string='أيام العمل')

    @api.depends('start_hour','end_hour')
    def _compute_name(self):
        for rec in self:
            def fmt(v):
                n = round(v*60)
                return '%02d:%02d' % (n//60,n%60)
            rec.name = '%s - %s' % (fmt(rec.start_hour),fmt(rec.end_hour))

    def operates_on(self, day):
        self.ensure_one()
        return not self.weekday_ids or str(day.weekday()) in self.weekday_ids.mapped('code')

    @api.constrains('start_hour','end_hour','capacity','branch_id','weekday_ids','active')
    def _check_period(self):
        all_days = set(self.env['ycc.weekday'].search([]).ids)
        for rec in self:
            if not (0 <= rec.start_hour < rec.end_hour <= 24) or rec.capacity < 1:
                raise ValidationError(_('Invalid period or capacity.'))
            if not rec.active: continue
            own = set(rec.weekday_ids.ids) or all_days
            others = self.search([('branch_id','=',rec.branch_id.id),('active','=',True),('id','!=',rec.id)])
            for other in others:
                days = set(other.weekday_ids.ids) or all_days
                if own & days and rec.start_hour < other.end_hour and other.start_hour < rec.end_hour:
                    raise ValidationError(_('Overlapping periods are not allowed.'))

class YCCException(models.Model):
    _name = 'ycc.exception'
    _description = 'إغلاق فترات الحجز'
    branch_id = fields.Many2one('ycc.branch',required=True,ondelete='cascade')
    date = fields.Date(required=True)
    slot_id = fields.Many2one('ycc.slot',string='الفترة (فارغ يعني كامل اليوم)')
    reason = fields.Char(required=True)

    @api.constrains('slot_id','branch_id')
    def _check_slot(self):
        for rec in self:
            if rec.slot_id and rec.slot_id.branch_id != rec.branch_id:
                raise ValidationError(_('The period must belong to the branch.'))

class YCCService(models.Model):
    _name = 'ycc.service'
    _description = 'خدمات العناية بالسيارات'
    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    estimated_hours = fields.Float(string='مدة التنفيذ التقديرية',default=2)
    price = fields.Float(string='السعر')

class YCCAppointment(models.Model):
    _name = 'ycc.appointment'
    _description = 'حجز موعد العناية'
    _inherit = ['mail.thread','mail.activity.mixin']
    _order = 'date desc,id desc'
    name = fields.Char(default='New',readonly=True,copy=False)
    branch_id = fields.Many2one('ycc.branch',string='الفرع',required=True,tracking=True)
    slot_id = fields.Many2one('ycc.slot',string='الفترة',required=True,tracking=True)
    date = fields.Date(string='تاريخ الموعد',required=True,default=fields.Date.context_today,tracking=True)
    partner_id = fields.Many2one('res.partner',string='العميل',required=True,tracking=True)
    phone = fields.Char(string='الجوال')
    vehicle_plate = fields.Char(string='لوحة السيارة',required=True)
    vehicle_model = fields.Char(string='السيارة والموديل',required=True)
    service_id = fields.Many2one('ycc.service',string='الخدمة',required=True)
    agent_id = fields.Many2one('res.users',string='المندوب',default=lambda self:self.env.user)
    notes = fields.Text(string='الملاحظات')
    state = fields.Selection([('provisional','مبدئي'),('contacting','جاري التواصل'),('confirmed','مؤكد'),('expired','منتهي'),('cancelled','ملغي'),('done','وصلت السيارة'),('no_show','لم يحضر')],string='الحالة',default='provisional',required=True,tracking=True)
    hold_until = fields.Datetime(string='انتهاء الحجز المبدئي',readonly=True,copy=False)
    contact_ids = fields.One2many('ycc.contact','appointment_id',string='سجل التواصل')
    next_contact_at = fields.Datetime(string='موعد المتابعة القادم')
    company_id = fields.Many2one('res.company',related='branch_id.company_id',store=True,readonly=True)

    def _occupies(self, now=None):
        self.ensure_one()
        now = fields.Datetime.from_string(now or fields.Datetime.now())
        return self.state in ('confirmed','done') or (self.state in ('provisional','contacting') and self.hold_until and fields.Datetime.from_string(self.hold_until) > now)

    def _check_capacity(self):
        now = fields.Datetime.now()
        for rec in self:
            if not rec.slot_id.active or rec.slot_id.branch_id != rec.branch_id:
                raise ValidationError(_('Invalid branch period.'))
            if not rec.slot_id.operates_on(fields.Date.from_string(rec.date)):
                raise ValidationError(_('This period is not available on this weekday.'))
            if self.env['ycc.exception'].search_count([('branch_id','=',rec.branch_id.id),('date','=',rec.date),'|',('slot_id','=',False),('slot_id','=',rec.slot_id.id)]):
                raise ValidationError(_('This period is closed.'))
            key = '%s:%s:%s' % (rec.branch_id.id,rec.slot_id.id,rec.date)
            self.env.cr.execute('SELECT pg_advisory_xact_lock(hashtext(%s))',[key])
            others = self.search([('branch_id','=',rec.branch_id.id),('slot_id','=',rec.slot_id.id),('date','=',rec.date),('id','!=',rec.id),('state','in',['provisional','contacting','confirmed','done'])])
            count = sum(1 for other in others if other._occupies(now))
            if rec._occupies(now) and count >= rec.slot_id.capacity:
                raise ValidationError(_('Booking period is full.'))

    @api.model
    def create(self, vals):
        vals = dict(vals)
        vals['name'] = self.env['ir.sequence'].next_by_code('ycc.appointment') or 'New'
        if vals.get('state','provisional') in ('provisional','contacting'):
            branch = self.env['ycc.branch'].browse(vals.get('branch_id'))
            vals['hold_until'] = fields.Datetime.to_string(fields.Datetime.from_string(fields.Datetime.now())+timedelta(minutes=branch.provisional_minutes or 120))
        rec = super().create(vals)
        rec._check_capacity()
        return rec

    def write(self, vals):
        vals = dict(vals)
        if 'hold_until' in vals and not self.env.user.has_group('base.group_system'):
            raise UserError(_('Only administrators may edit hold expiry.'))
        if vals.get('state') in ('provisional','contacting') and 'hold_until' not in vals:
            for rec in self:
                if rec.state not in ('provisional','contacting') or not rec._occupies():
                    raise UserError(_('Expired holds cannot be reopened. Create a new booking.'))
        result = super().write(vals)
        if set(vals) & {'branch_id','slot_id','date','state','hold_until'}:
            self._check_capacity()
        return result

    def action_contacting(self): self.write({'state':'contacting'})
    def action_confirm(self):
        for rec in self:
            if rec.state not in ('provisional','contacting') or not rec._occupies():
                raise UserError(_('Only active provisional bookings can be confirmed.'))
            rec.write({'state':'confirmed'})
    def action_cancel(self): self.write({'state':'cancelled'})
    def action_done(self): self.write({'state':'done'})
    def action_no_show(self): self.write({'state':'no_show'})

    @api.model
    def cron_expire_holds(self):
        self.search([('state','in',['provisional','contacting']),('hold_until','!=',False),('hold_until','<=',fields.Datetime.now())]).write({'state':'expired'})

class YCCContact(models.Model):
    _name = 'ycc.contact'
    _description = 'سجل التواصل مع العميل'
    _order = 'contact_at desc,id desc'
    appointment_id = fields.Many2one('ycc.appointment',required=True,ondelete='cascade')
    contact_at = fields.Datetime(string='التاريخ',required=True,default=fields.Datetime.now)
    user_id = fields.Many2one('res.users',string='المندوب',required=True,default=lambda self:self.env.user)
    channel = fields.Selection([('call','اتصال'),('whatsapp','واتساب'),('sms','رسالة'),('other','أخرى')],string='الوسيلة',required=True,default='call')
    result = fields.Selection([('no_answer','لم يرد'),('follow_up','متابعة'),('reschedule','تغيير موعد'),('confirmed','تأكيد'),('other','أخرى')],string='النتيجة',required=True,default='follow_up')
    note = fields.Text(string='التفاصيل',required=True)
    next_contact_at = fields.Datetime(string='المتابعة القادمة')
