# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from datetime import datetime
from odoo.exceptions import UserError


class YCCInstallationOrder(models.Model):
    _inherit = 'wo.installation.order.mst'

    check_date = fields.Date(string='تاريخ موعد التشييك', tracking=True, copy=False, index=True)
    ycc_check_date_editable = fields.Boolean(
        string='السماح بتحديد موعد التشييك', compute='_compute_ycc_check_date_editable')

    @api.depends('create_invoice_id', 'create_invoice_id.state')
    def _compute_ycc_check_date_editable(self):
        for order in self:
            order.ycc_check_date_editable = bool(
                order.create_invoice_id and order.create_invoice_id.state == 'posted')

    def _ycc_assert_check_date_editable(self, vals):
        if 'check_date' not in vals:
            return
        for order in self:
            if order.check_date != vals.get('check_date') and not (
                    order.create_invoice_id and order.create_invoice_id.state == 'posted'):
                raise UserError(_('لا يمكن تحديد أو تغيير موعد التشييك قبل ترحيل فاتورة أمر التركيب.'))

    def write(self, vals):
        self._ycc_assert_check_date_editable(vals)
        return super(YCCInstallationOrder, self).write(vals)


    @api.constrains('check_date', 'branch_id')
    def _check_daily_check_capacity(self):
        for order in self:
            if not order.check_date or not order.branch_id:
                continue
            config = self.env['ycc.branch'].search([('branch_id', '=', order.branch_id.id), ('active', '=', True)], limit=1)
            if not config:
                continue
            self.env.cr.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', ['ycc:check:%s' % order.branch_id.id])
            self.env.cr.execute('SELECT COUNT(*) FROM wo_installation_order_mst WHERE branch_id = %s AND check_date = %s', (order.branch_id.id, order.check_date))
            count = self.env.cr.fetchone()[0]
            if count > config.check_capacity:
                raise UserError(_('اكتملت سعة التشييك ليوم %s في هذا الفرع (%s سيارات). اختر تاريخًا آخر.') % (order.check_date, config.check_capacity))

    ycc_appointment_id = fields.Many2one('ycc.appointment', string='حجز الموعد المصدر',
                                         readonly=True, copy=False, index=True)

    ycc_booking_date = fields.Date(string='تاريخ الحجز المخطط', related='ycc_appointment_id.date', readonly=True)
    ycc_date_difference_notice = fields.Text(string='ملاحظة اختلاف التواريخ', compute='_compute_ycc_date_difference_notice')

    @api.depends('order_date', 'ycc_appointment_id', 'ycc_appointment_id.date')
    def _compute_ycc_date_difference_notice(self):
        for order in self:
            appt = order.ycc_appointment_id
            if not appt or not appt.date or not order.order_date:
                order.ycc_date_difference_notice = False
                continue
            booking = fields.Date.from_string(appt.date)
            request = fields.Date.from_string(order.order_date)
            days = (request - booking).days
            if days > 0:
                order.ycc_date_difference_notice = _('تنبيه: أمر التركيب بعد موعد الحجز بـ %s يوم. تحقق هل تأخرت السيارة أم تأخر تسجيل الأمر. سيُوثّق الفرق في سجل الحجز وأمر التركيب.') % days
            elif days < 0:
                order.ycc_date_difference_notice = _('تنبيه: أمر التركيب قبل موعد الحجز بـ %s يوم. تأكد من موعد الاستقبال. سيُوثّق الفرق في سجل الحجز وأمر التركيب.') % abs(days)
            else:
                order.ycc_date_difference_notice = False

    @api.model
    def create(self, vals):
        appt_id = self.env.context.get('ycc_source_appointment_id')
        if not appt_id:
            return super(YCCInstallationOrder, self).create(vals)
        appt = self.env['ycc.appointment'].browse(appt_id).exists()
        if not appt or appt.state != 'done':
            raise UserError(_('يجب تسجيل وصول السيارة أولاً.'))
        # Serialise creation for the same appointment and branch.
        self.env.cr.execute('SELECT id FROM ycc_appointment WHERE id = %s FOR UPDATE', (appt.id,))
        appt.invalidate_cache(['installation_order_id'])
        if appt.installation_order_id:
            raise UserError(_('تم إنشاء أمر تركيب لهذا الحجز بالفعل؛ افتح الأمر الموجود.'))
        branch_id = appt.branch_id.branch_id.id
        if vals.get('branch_id', branch_id) != branch_id:
            raise UserError(_('فرع أمر التركيب يجب أن يطابق فرع الحجز.'))
        # Original qimanhd_wo_v3 default _get_sequence() uses env.user.branch_id,
        # not the order branch, and can reuse an existing seq for another branch.
        # Lock the actual branch row and allocate the next number there.
        self.env.cr.execute('SELECT id FROM custom_branches WHERE id = %s FOR UPDATE', (branch_id,))
        self.env.cr.execute('SELECT COALESCE(MAX(seq), 0) + 1 FROM wo_installation_order_mst WHERE branch_id = %s', (branch_id,))
        # Order request date is the real date of order creation; booking date is
        # kept separately. Never backdate the request to the appointment.
        if not appt.date:
            raise UserError(_('يجب تحديد تاريخ بداية الحجز قبل إنشاء أمر التركيب.'))
        actual_request_date = fields.Date.context_today(self)
        vals = dict(vals, branch_id=branch_id, seq=self.env.cr.fetchone()[0],
                    agency_id=appt.agency_id.id or False,
                    order_date=actual_request_date, ycc_appointment_id=appt.id, state='draft')
        order = super(YCCInstallationOrder, self).create(vals)
        appt.with_context(ycc_source_appointment_id=appt.id).write({'installation_order_id': order.id, 'state': 'installation_created'})
        booking_date = fields.Date.from_string(appt.date)
        request_date = fields.Date.from_string(actual_request_date)
        difference = (request_date - booking_date).days
        if difference > 0:
            explanation = _('أُنشئ أمر التركيب بعد تاريخ الحجز بـ %s يوم. يرجى مراجعة ما إذا كان السبب تأخر وصول السيارة أو تأخر تسجيل الأمر.') % difference
        elif difference < 0:
            explanation = _('أُنشئ أمر التركيب قبل تاريخ الحجز بـ %s يوم؛ يرجى مراجعة موعد الاستقبال.') % abs(difference)
        else:
            explanation = _('تاريخ طلب أمر التركيب مطابق لتاريخ الحجز.')
        audit = _('مرجع تواريخ الحجز/التركيب: الحجز %s؛ تاريخ الحجز المخطط %s؛ تاريخ ووقت الوصول المسجل %s؛ تاريخ طلب أمر التركيب الفعلي %s؛ أنشأه %s. %s') % (
            appt.name, appt.date, appt.actual_arrival_at or _('غير مسجل'),
            actual_request_date, self.env.user.name, explanation)
        appt.message_post(body=audit)
        order.message_post(body=audit)
        if appt.notes:
            order.message_post(body=_('ملاحظات الحجز: %s') % appt.notes)
        return order

    def write(self, vals):
        if (self.env.user.has_group('yousentech_car_appointments.group_ycc_sales_arrival')
                and not (self.env.user.has_group('base.group_system') or self.env.user.has_group('yousentech_car_appointments.group_ycc_manager'))
                and any(r.ycc_appointment_id for r in self)):
            raise UserError(_('مندوب الوصول لا يمكنه تعديل أمر التركيب بعد إنشائه.'))
        return super(YCCInstallationOrder, self).write(vals)

    def action_ycc_open_full_order(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('أمر التركيب'),
            'res_model': self._name, 'res_id': self.id,
            'views': [(self.env.ref('qimamhd_wo_v3.wo_installation_order_view').id, 'form')],
            'view_mode': 'form', 'target': 'current',
        }
