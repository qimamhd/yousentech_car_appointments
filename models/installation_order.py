# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class YCCInstallationOrder(models.Model):
    _inherit = 'wo.installation.order.mst'

    ycc_appointment_id = fields.Many2one('ycc.appointment', string='حجز الموعد المصدر',
                                         readonly=True, copy=False, index=True)

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
        vals = dict(vals, branch_id=branch_id, seq=self.env.cr.fetchone()[0],
                    ycc_appointment_id=appt.id, state='draft')
        order = super(YCCInstallationOrder, self).create(vals)
        appt.write({'installation_order_id': order.id})
        if appt.notes:
            order.message_post(body=_('ملاحظات الحجز: %s') % appt.notes)
        return order

    def action_ycc_open_full_order(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('أمر التركيب'),
            'res_model': self._name, 'res_id': self.id,
            'views': [(self.env.ref('qimamhd_wo_v3.wo_installation_order_view').id, 'form')],
            'view_mode': 'form', 'target': 'current',
        }
