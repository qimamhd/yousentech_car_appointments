# -*- coding: utf-8 -*-
"""V6.74 — Customer experience after service (تجربة العميل).

Flow: a booking reaches "invoice closed" (posted invoice on its installation
order). N days after the invoice date (per branch, default 5) a daily job opens
a feedback task and schedules an activity for the booking creator. A booking
user records the call: rating, channel and notes; no answer retries the next
day (3 attempts), a dissatisfied rating alerts the appointment managers.
"""
from datetime import timedelta
from odoo import api, fields, models, _
from odoo.exceptions import UserError

RATINGS = [
    ('5', 'راضٍ جدًا'),
    ('4', 'راضٍ'),
    ('3', 'محايد'),
    ('2', 'غير راضٍ'),
    ('1', 'غير راضٍ جدًا'),
]
CHANNELS = [('call', 'اتصال'), ('whatsapp', 'واتساب'), ('sms', 'رسالة'), ('visit', 'زيارة / حضور')]
MAX_ATTEMPTS = 3
# Only invoices closed recently open a task, so installing the feature does not
# flood the team with calls for old, long-closed bookings.
LOOKBACK_DAYS = 30


class YCCBranchFeedback(models.Model):
    _inherit = 'ycc.branch'

    feedback_delay_days = fields.Integer(
        string='التواصل لتجربة العميل بعد إقفال الفاتورة (أيام)', default=5, required=True,
        help='عدد الأيام بعد تاريخ فاتورة أمر التركيب حتى يظهر تنبيه التواصل مع العميل لتقييم تجربته.')


class YCCFeedback(models.Model):
    _name = 'ycc.feedback'
    _description = 'تجربة العميل بعد الخدمة'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'state_sequence, due_date asc, id desc'
    _rec_name = 'name'

    name = fields.Char(string='المرجع', compute='_compute_name', store=True)
    appointment_id = fields.Many2one('ycc.appointment', string='الحجز', required=True, ondelete='cascade', index=True)
    branch_id = fields.Many2one(related='appointment_id.branch_id', store=True, string='الفرع')
    custom_branch_id = fields.Many2one(related='appointment_id.custom_branch_id', store=True, string='الفرع الفعلي')
    partner_id = fields.Many2one(related='appointment_id.partner_id', store=True, string='العميل')
    phone = fields.Char(related='appointment_id.phone', string='الجوال')
    vehicle_plate = fields.Char(related='appointment_id.vehicle_plate', string='اللوحة')
    installation_order_id = fields.Many2one(related='appointment_id.installation_order_id', string='أمر التركيب')
    booking_user_id = fields.Many2one(related='appointment_id.create_uid', store=True, string='منشئ الحجز')
    invoice_date = fields.Date(string='تاريخ إقفال الفاتورة', readonly=True)
    due_date = fields.Date(string='موعد التواصل', required=True, tracking=True, index=True)
    state = fields.Selection([
        ('due', 'بانتظار التواصل'),
        ('done', 'تم التقييم'),
        ('unreachable', 'تعذر التواصل'),
        ('declined', 'رفض التقييم'),
    ], string='الحالة', default='due', required=True, tracking=True, index=True)
    state_sequence = fields.Integer(compute='_compute_state_sequence', store=True)
    attempts = fields.Integer(string='محاولات بدون رد', default=0, tracking=True)
    assigned_user_id = fields.Many2one('res.users', string='المسؤول عن التواصل', tracking=True)
    rating = fields.Selection(RATINGS, string='مدى رضا العميل', tracking=True)
    rating_value = fields.Integer(string='التقييم (1-5)', compute='_compute_rating_value', store=True, group_operator='avg')
    channel = fields.Selection(CHANNELS, string='قناة التواصل')
    note = fields.Text(string='ملاحظات العميل')
    done_by = fields.Many2one('res.users', string='سجّل التقييم', readonly=True)
    done_at = fields.Datetime(string='وقت التسجيل', readonly=True)
    is_unhappy = fields.Boolean(string='غير راضٍ', compute='_compute_rating_value', store=True)
    is_overdue = fields.Boolean(string='متأخر', compute='_compute_is_overdue', search='_search_is_overdue')

    _sql_constraints = [('ycc_feedback_unique_booking', 'unique(appointment_id)',
                         'يوجد سجل تجربة عميل لهذا الحجز بالفعل.')]

    @api.depends('appointment_id.name')
    def _compute_name(self):
        for rec in self:
            rec.name = _('تجربة العميل — %s') % (rec.appointment_id.name or '')

    @api.depends('state')
    def _compute_state_sequence(self):
        order = {'due': 0, 'done': 1, 'unreachable': 2, 'declined': 3}
        for rec in self:
            rec.state_sequence = order.get(rec.state, 9)

    @api.depends('rating')
    def _compute_rating_value(self):
        for rec in self:
            rec.rating_value = int(rec.rating) if rec.rating else 0
            rec.is_unhappy = bool(rec.rating) and int(rec.rating) <= 2

    def _compute_is_overdue(self):
        today = fields.Date.context_today(self)
        for rec in self:
            rec.is_overdue = rec.state == 'due' and rec.due_date and rec.due_date < today

    def _search_is_overdue(self, operator, value):
        today = fields.Date.context_today(self)
        positive = (operator == '=' and value) or (operator == '!=' and not value)
        domain = [('state', '=', 'due'), ('due_date', '<', today)]
        return domain if positive else ['!', '&'] + domain

    # ------------------------------------------------------------------ helpers
    @api.model
    def _invoice_of(self, appointment):
        order = appointment.installation_order_id
        invoice = order.create_invoice_id if order and 'create_invoice_id' in order._fields else False
        return invoice if invoice and invoice.state == 'posted' else False

    @api.model
    def _invoice_day(self, invoice):
        for name in ('invoice_date', 'date'):
            if name in invoice._fields and invoice[name]:
                return fields.Date.to_date(invoice[name])
        return fields.Date.to_date(invoice.write_date) if invoice.write_date else fields.Date.context_today(self)

    def _responsible(self, appointment):
        """Booking creator when still an active booking user, else nobody (any booking user can act)."""
        user = appointment.create_uid
        if user and user.active and user.has_group('yousentech_car_appointments.group_ycc_booking'):
            return user
        return self.env['res.users']

    def _schedule_call_activity(self):
        todo = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
        for rec in self.filtered(lambda r: r.state == 'due'):
            rec.activity_unlink(['mail.mail_activity_data_todo'])
            if not rec.assigned_user_id:
                continue
            rec.activity_schedule(
                activity_type_id=todo.id if todo else False,
                date_deadline=max(rec.due_date, fields.Date.context_today(rec)),
                summary=_('تواصل مع العميل لتقييم تجربة الخدمة'),
                note=_('العميل: %s — الجوال: %s — الحجز: %s') % (rec.partner_id.name or '', rec.phone or '', rec.appointment_id.name),
                user_id=rec.assigned_user_id.id)

    def _close_activities(self, feedback_text):
        for rec in self:
            for activity in rec.activity_ids:
                activity.action_feedback(feedback=feedback_text)

    # --------------------------------------------------------------- automation
    @api.model
    def cron_create_feedback_tasks(self):
        """Daily: open feedback tasks for bookings whose invoice was closed N days ago."""
        Appt = self.env['ycc.appointment'].sudo()
        today = fields.Date.context_today(self)
        candidates = Appt.search([('installation_order_id', '!=', False), ('feedback_ids', '=', False),
                                  ('is_check_only', '=', False)])
        created = self.browse()
        for appt in candidates:
            invoice = self._invoice_of(appt)
            if not invoice:
                continue
            closed_on = self._invoice_day(invoice)
            if (today - closed_on).days > LOOKBACK_DAYS + (appt.branch_id.feedback_delay_days or 5):
                continue
            due = closed_on + timedelta(days=appt.branch_id.feedback_delay_days or 5)
            if due > today:
                continue
            created |= self.sudo().create({
                'appointment_id': appt.id, 'invoice_date': closed_on, 'due_date': due,
                'assigned_user_id': self._responsible(appt).id or False,
            })
        created._schedule_call_activity()
        for rec in created:
            rec.appointment_id.message_post(body=_('حان وقت التواصل مع العميل لتقييم تجربة الخدمة (فاتورة مقفلة بتاريخ %s).') % rec.invoice_date)
        return len(created)

    # ------------------------------------------------------------------ actions
    def action_open_feedback_wizard(self):
        self.ensure_one()
        if not self.appointment_id._ycc_can_book():
            raise UserError(_('تسجيل تجربة العميل متاح لموظفي الحجوزات ومدير المواعيد.'))
        if self.state != 'due':
            raise UserError(_('تم إغلاق سجل تجربة العميل هذا.'))
        return {
            'type': 'ir.actions.act_window', 'name': _('تجربة العميل — %s') % (self.partner_id.name or ''),
            'res_model': 'ycc.feedback.wizard', 'view_mode': 'form', 'target': 'new',
            'context': {'default_feedback_id': self.id},
        }

    def action_reopen(self):
        """Manager: reopen a closed feedback (e.g. to call again)."""
        if not self.env['ycc.appointment']._ycc_manager():
            raise UserError(_('إعادة فتح تجربة العميل متاحة لمدير المواعيد فقط.'))
        for rec in self:
            rec.write({'state': 'due', 'due_date': fields.Date.context_today(rec), 'attempts': 0})
            rec._schedule_call_activity()
        return True


class YCCFeedbackWizard(models.TransientModel):
    _name = 'ycc.feedback.wizard'
    _description = 'تسجيل تجربة العميل'

    feedback_id = fields.Many2one('ycc.feedback', readonly=True)
    partner_id = fields.Many2one(related='feedback_id.partner_id', string='العميل')
    phone = fields.Char(related='feedback_id.phone', string='الجوال')
    appointment_id = fields.Many2one(related='feedback_id.appointment_id', string='الحجز')
    vehicle_plate = fields.Char(related='feedback_id.vehicle_plate', string='اللوحة')
    invoice_date = fields.Date(related='feedback_id.invoice_date', string='تاريخ إقفال الفاتورة')
    attempts = fields.Integer(related='feedback_id.attempts', string='محاولات سابقة بدون رد')
    outcome = fields.Selection([
        ('done', 'تم التواصل وقيّم العميل'),
        ('no_answer', 'لم يرد'),
        ('declined', 'رفض التقييم'),
    ], string='نتيجة التواصل', default='done')
    channel = fields.Selection(CHANNELS, string='قناة التواصل', default='call')
    rating = fields.Selection(RATINGS, string='مدى رضا العميل')
    note = fields.Text(string='ملاحظات العميل')

    def action_apply(self):
        self.ensure_one()
        rec = self.feedback_id.sudo() if self.feedback_id else False
        if not rec:
            raise UserError(_('لا يوجد سجل تجربة عميل.'))
        if not self.feedback_id.appointment_id._ycc_can_book():
            raise UserError(_('تسجيل تجربة العميل متاح لموظفي الحجوزات ومدير المواعيد.'))
        if rec.state != 'due':
            raise UserError(_('تم إغلاق سجل تجربة العميل هذا.'))
        if not self.outcome:
            raise UserError(_('اختر نتيجة التواصل.'))
        user = self.env.user
        note = (self.note or '').strip()
        appt = rec.appointment_id
        if self.outcome == 'done':
            if not self.rating:
                raise UserError(_('اختر مدى رضا العميل.'))
            if int(self.rating) <= 2 and not note:
                raise UserError(_('اكتب ملاحظات العميل عند عدم الرضا، حتى يعالجها مدير المواعيد.'))
            label = dict(RATINGS)[self.rating]
            rec.write({'state': 'done', 'rating': self.rating, 'channel': self.channel, 'note': note,
                       'done_by': user.id, 'done_at': fields.Datetime.now()})
            rec._close_activities(_('تم التقييم: %s') % label)
            body = _('تجربة العميل: %s (%s) — بواسطة %s.%s') % (
                label, dict(CHANNELS).get(self.channel, ''), user.name, (' ' + _('الملاحظات: %s') % note) if note else '')
            appt.message_post(body=body)
            rec.message_post(body=body)
            if int(self.rating) <= 2:
                self._alert_managers(rec, label, note)
        elif self.outcome == 'no_answer':
            attempts = rec.attempts + 1
            if attempts >= MAX_ATTEMPTS:
                rec.write({'state': 'unreachable', 'attempts': attempts, 'done_by': user.id,
                           'done_at': fields.Datetime.now(), 'channel': self.channel, 'note': note})
                rec._close_activities(_('تعذر التواصل بعد %s محاولات') % attempts)
                appt.message_post(body=_('تجربة العميل: تعذر التواصل بعد %s محاولات (آخرها بواسطة %s).') % (attempts, user.name))
            else:
                rec.write({'attempts': attempts, 'due_date': fields.Date.context_today(self) + timedelta(days=1)})
                rec._schedule_call_activity()
                rec.message_post(body=_('لم يرد العميل (محاولة %s من %s) — بواسطة %s. أُعيدت المتابعة غدًا.')
                                 % (attempts, MAX_ATTEMPTS, user.name))
        else:
            rec.write({'state': 'declined', 'channel': self.channel, 'note': note,
                       'done_by': user.id, 'done_at': fields.Datetime.now()})
            rec._close_activities(_('رفض العميل التقييم'))
            appt.message_post(body=_('تجربة العميل: رفض العميل التقييم — بواسطة %s.') % user.name)
        return {'type': 'ir.actions.act_window_close'}

    def _alert_managers(self, rec, label, note):
        group = self.env.ref('yousentech_car_appointments.group_ycc_manager', raise_if_not_found=False)
        if not group:
            return
        managers = group.users.filtered(lambda u: u.active)
        branch = rec.custom_branch_id
        if branch and managers and 'allowed_branch_ids' in managers._fields:
            in_branch = managers.filtered(lambda u: branch in u.allowed_branch_ids)
            managers = in_branch or managers
        todo = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
        for manager in managers[:5]:
            rec.activity_schedule(
                activity_type_id=todo.id if todo else False,
                date_deadline=fields.Date.context_today(self),
                summary=_('عميل غير راضٍ: %s') % (rec.partner_id.name or ''),
                note=_('التقييم: %s — الملاحظات: %s — الجوال: %s') % (label, note or '-', rec.phone or ''),
                user_id=manager.id)


class YCCAppointmentFeedback(models.Model):
    _inherit = 'ycc.appointment'

    feedback_ids = fields.One2many('ycc.feedback', 'appointment_id', string='تجربة العميل')
    feedback_id = fields.Many2one('ycc.feedback', compute='_compute_feedback_id', string='تجربة العميل')
    feedback_state = fields.Selection(related='feedback_id.state', string='حالة تجربة العميل')
    feedback_rating = fields.Selection(related='feedback_id.rating', string='مدى رضا العميل')
    feedback_due_date = fields.Date(related='feedback_id.due_date', string='موعد التواصل')
    feedback_done_by = fields.Many2one(related='feedback_id.done_by', string='سجّل التقييم')
    feedback_done_at = fields.Datetime(related='feedback_id.done_at', string='وقت التسجيل')
    feedback_note = fields.Text(related='feedback_id.note', string='ملاحظات العميل')
    feedback_attempts = fields.Integer(related='feedback_id.attempts', string='محاولات بدون رد')

    @api.depends('feedback_ids')
    def _compute_feedback_id(self):
        for rec in self:
            rec.feedback_id = rec.feedback_ids[:1]

    def action_open_feedback(self):
        self.ensure_one()
        if not self.feedback_id:
            raise UserError(_('لم يحن بعد موعد التواصل مع العميل لتقييم تجربته.'))
        return self.feedback_id.action_open_feedback_wizard()

    def action_view_feedback(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'ycc.feedback', 'res_id': self.feedback_id.id,
                'view_mode': 'form', 'views': [(False, 'form')], 'target': 'current'}
