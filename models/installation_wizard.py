# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class YCCInstallationWizard(models.TransientModel):
    _name = 'ycc.installation.wizard'
    _description = 'رأس أمر تركيب من موعد وصول السيارة'

    appointment_id = fields.Many2one('ycc.appointment', required=True, readonly=True)
    partner_id = fields.Many2one('res.partner', string='العميل', required=True)
    partner_mobile = fields.Char(string='رقم الجوال')
    branch_id = fields.Many2one('custom.branches', string='الفرع', required=True, readonly=True)
    order_date = fields.Date(string='تاريخ الطلب', required=True, default=fields.Date.context_today)
    car_manuf_id = fields.Many2one('wo.car.manufactory', string='الشركة المصنعة')
    car_type_id = fields.Many2one('wo.car.types', string='نوع السيارة')
    car_size_id = fields.Many2one('wo.car.sizes', string='حجم السيارة', required=True)
    car_panel_no = fields.Char(string='رقم اللوحة')
    delivery_date = fields.Date(string='موعد التسليم')
    delivery_period = fields.Many2one('wo.delivery.period', string='فترة التسليم')
    notes = fields.Text(string='ملاحظات الحجز')

    @api.model
    def default_get(self, field_names):
        vals = super(YCCInstallationWizard, self).default_get(field_names)
        appt = self.env['ycc.appointment'].browse(self.env.context.get('default_appointment_id') or 0).exists()
        if appt:
            vals.update({
                'appointment_id': appt.id,
                'partner_id': appt.partner_id.id,
                'partner_mobile': appt.phone or appt.partner_id.mobile or '',
                'branch_id': appt.branch_id.branch_id.id,
                'order_date': fields.Date.context_today(self),
                'car_manuf_id': appt.car_manuf_id.id or False,
                'car_type_id': appt.car_type_id.id or False,
                'car_panel_no': appt.vehicle_plate or '',
                'delivery_date': appt.end_date or appt.date or False,
                'notes': appt.notes or '',
            })
        return vals

    def action_create_installation(self):
        self.ensure_one()
        appt = self.appointment_id
        # Lock the appointment to prevent two simultaneous requests creating two orders.
        self.env.cr.execute('SELECT id FROM ycc_appointment WHERE id = %s FOR UPDATE', (appt.id,))
        appt.invalidate_cache(['installation_order_id'])
        if appt.installation_order_id:
            return appt.action_open_installation_order()
        if appt.state != 'done':
            raise UserError(_('لا يمكن إنشاء أمر تركيب قبل وصول السيارة.'))
        if self.branch_id != appt.branch_id.branch_id:
            raise UserError(_('فرع أمر التركيب يجب أن يطابق فرع الحجز.'))
        Order = self.env['wo.installation.order.mst']
        Order.check_access_rights('create')
        vals = {
            'partner_id': self.partner_id.id,
            'partner_mobile': self.partner_mobile or '',
            'branch_id': self.branch_id.id,
            'company_id': appt.company_id.id or self.env.company.id,
            'order_date': self.order_date,
            'car_manuf_id': self.car_manuf_id.id or False,
            'car_type_id': self.car_type_id.id or False,
            'car_size_id': self.car_size_id.id,
            'car_panel_no': self.car_panel_no or False,
            'delivery_date': self.delivery_date or False,
            'delivery_period': self.delivery_period.id or False,
        }
        # The original work-order model supplies its own sequence and draft state.
        order = Order.with_context(default_branch_id=self.branch_id.id).create(vals)
        appt.write({'installation_order_id': order.id})
        if self.notes:
            order.message_post(body=_('ملاحظات الحجز: %s') % self.notes)
        order.message_post(body=_('تم إنشاء أمر التركيب من الحجز %s') % appt.name)
        return appt.action_open_installation_order()
