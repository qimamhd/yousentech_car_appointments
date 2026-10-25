# -*- coding: utf-8 -*-
from datetime import timedelta
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError

class YCCBranch(models.Model):
    _name = 'ycc.branch'
    _description = 'إعدادات مواعيد الفرع'
    _rec_name = 'branch_id'

    branch_id = fields.Many2one('custom.branches', string='الفرع', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one('res.company', string='الشركة', default=lambda self: self.env.company)
    active = fields.Boolean(default=True)
    capacity = fields.Integer(string='القدرة الاستيعابية اليومية للفرع (سيارات)', default=4, required=True)
    provisional_minutes = fields.Integer(string='صلاحية الحجز المبدئي بالدقائق', default=120, required=True)
    slot_ids = fields.One2many('ycc.slot', 'branch_id', string='فترات الحجز')
    exception_ids = fields.One2many('ycc.exception', 'branch_id', string='الاستثناءات')
    _sql_constraints = [('unique_branch', 'unique(branch_id)', 'يوجد إعداد مواعيد لهذا الفرع بالفعل.')]

    def write(self, vals):
        if 'capacity' in vals:
            for rec in self:
                new_capacity = vals['capacity']
                if new_capacity < 1:
                    raise ValidationError(_('القدرة الاستيعابية يجب أن تكون أكبر من صفر.'))
                if new_capacity < rec.capacity:
                    self.env.cr.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', ['ycc:branch:%s' % rec.id])
                    appointments = self.env['ycc.appointment'].search([
                        ('branch_id', '=', rec.id),
                        ('state', 'in', ['provisional', 'contacting', 'confirmed', 'done', 'installation_created', 'postponed'])
                    ])
                    occupied = {}
                    for booking in appointments:
                        if booking._occupies() and booking.slot_id and booking.date:
                            # Each vehicle consumes one daily place even across many slots.
                            for day in set(day for day, _slot in booking._covered_periods()):
                                occupied[day] = occupied.get(day, 0) + 1
                                if occupied[day] > new_capacity:
                                    raise ValidationError(_('لا يمكن خفض السعة اليومية: حجوزات يوم %s تتجاوز السعة الجديدة.') % day)
        return super().write(vals)

    @api.constrains('provisional_minutes', 'capacity')
    def _check_minutes(self):
        for rec in self:
            if rec.capacity <= 0:
                raise ValidationError(_('القدرة الاستيعابية يجب أن تكون أكبر من صفر.'))
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
    capacity = fields.Integer(string='السعة اليومية للفرع (للعرض فقط)', related='branch_id.capacity', readonly=True)
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

    @api.constrains('start_hour','end_hour','branch_id','weekday_ids','active')
    def _check_period(self):
        all_days = set(self.env['ycc.weekday'].search([]).ids)
        for rec in self:
            if not (0 <= rec.start_hour < rec.end_hour <= 24):
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
    end_date = fields.Date(string='نهاية الإجازة (اختياري)')
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

class YCCAppointment(models.Model):
    _name = 'ycc.appointment'
    _description = 'حجز موعد العناية'
    _inherit = ['mail.thread','mail.activity.mixin']
    _order = 'date desc,id desc'
    name = fields.Char(default='New',readonly=True,copy=False)
    branch_id = fields.Many2one('ycc.branch',string='الفرع',tracking=True)
    custom_branch_id = fields.Many2one('custom.branches', string='الفرع الفعلي (V3)',
                                       related='branch_id.branch_id', store=True, readonly=True)
    slot_id = fields.Many2one('ycc.slot',string='بداية الفترة',tracking=True)
    end_slot_id = fields.Many2one('ycc.slot',string='نهاية الفترة (اختياري)',tracking=True,help='اتركه فارغًا لحجز فترة واحدة، أو اختر نهاية الفترة لحجز فترات متتالية.')
    date = fields.Date(string='تاريخ بداية الحجز',default=fields.Date.context_today,tracking=True)
    end_date = fields.Date(string='تاريخ نهاية الحجز', tracking=True, help='اتركه فارغًا لحجز يوم واحد. يمكن أن تمتد السيارة لأيام متعددة.')
    partner_id = fields.Many2one('res.partner',string='العميل',required=True,tracking=True)
    phone = fields.Char(string='الجوال', required=True)
    vehicle_plate = fields.Char(string='لوحة السيارة')
    # Original free-text value retained for existing appointments and integrations.
    vehicle_model = fields.Char(string='وصف السيارة السابق', copy=False)
    car_manuf_id = fields.Many2one('wo.car.manufactory', string='الشركة المصنعة (قديم)', tracking=True)
    agency_id = fields.Many2one('wo.agency', string='الوكالة', tracking=True)
    # All vehicle types must remain selectable, including legacy types without a manufacturer.
    # New types inherit the selected manufacturer via the form context only.
    car_type_id = fields.Many2one('wo.car.types', string='نوع السيارة', tracking=True)

    def _validate_vehicle_selection(self):
        for rec in self:
            if not rec.car_type_id and not rec.vehicle_model:
                raise ValidationError(_('يرجى تحديد نوع السيارة.'))

    service_id = fields.Many2one('ycc.service',string='الخدمة')
    agent_id = fields.Many2one('res.users',string='المندوب',default=lambda self:self.env.user)
    notes = fields.Text(string='الملاحظات')
    state = fields.Selection([('provisional','مبدئي'),('contacting','جاري التواصل'),('confirmed','مؤكد'),('expired','منتهي'),('cancelled','ملغي'),('done','وصلت السيارة'),('installation_created','تم إنشاء أمر تركيب'),('no_show','لم يحضر'),('postponed','تم تأجيل الموعد')],string='الحالة',default='provisional',required=True,tracking=True)
    hold_until = fields.Datetime(string='انتهاء الحجز المبدئي',readonly=True,copy=False)
    was_postponed = fields.Boolean(string='تم تأجيله سابقًا', default=False, readonly=True, copy=False, tracking=True)
    postponement_count = fields.Integer(string='عدد مرات التأجيل', default=0, readonly=True, copy=False)
    contact_ids = fields.One2many('ycc.contact','appointment_id',string='سجل التواصل')
    next_contact_at = fields.Datetime(string='موعد المتابعة القادم')
    company_id = fields.Many2one('res.company',related='branch_id.company_id',store=True,readonly=True)
    actual_arrival_at = fields.Datetime(string='تاريخ ووقت وصول السيارة الفعلي', readonly=True, copy=False, tracking=True)
    installation_order_id = fields.Many2one('wo.installation.order.mst', string='أمر التركيب المرتبط', readonly=True, copy=False, tracking=True)
    service_stage = fields.Selection([
        ('provisional','حجز مبدئي'),('contacting','جاري التواصل'),('confirmed','حجز مؤكد'),
        ('done','وصلت السيارة'),('installation_created','تم إنشاء أمر تركيب'),
        ('completed','تم الإنجاز'),('invoice_closed','تم إقفال الفاتورة'),
        ('postponed','تم تأجيل الموعد'),('no_show','لم يحضر'),
        ('cancelled','ملغي'),('expired','منتهي')],
        string='مؤشر خدمة العملاء', compute='_compute_service_stage', readonly=True)

    @api.depends('state', 'installation_order_id', 'installation_order_id.state',
                 'installation_order_id.create_invoice_id',
                 'installation_order_id.create_invoice_id.state')
    def _compute_service_stage(self):
        for rec in self:
            stage = rec.state
            order = rec.installation_order_id
            # Installation order progress takes precedence over the booking's
            # historical state (e.g. a booking that was postponed and returned
            # to provisional). Never write back to the installation order.
            if order:
                invoice = order.create_invoice_id
                # Completion is the final customer-service stage and must
                # override a previously posted invoice (not vice versa).
                if order.state in ('execute_completed', 'complete_work'):
                    stage = 'completed'
                elif invoice and invoice.state == 'posted':
                    stage = 'invoice_closed'
                elif order.state != 'cancel_order' and stage in ('provisional', 'contacting', 'confirmed', 'done', 'postponed'):
                    stage = 'installation_created'
            rec.service_stage = stage

    installation_order_date = fields.Date(string='تاريخ طلب أمر التركيب', related='installation_order_id.order_date', readonly=True, store=False)
    installation_date_notice = fields.Char(string='ملاحظة فرق التواريخ', compute='_compute_installation_date_notice', readonly=True)

    @api.depends('date', 'installation_order_id', 'installation_order_id.order_date')
    def _compute_installation_date_notice(self):
        for rec in self:
            if not rec.date or not rec.installation_order_date:
                rec.installation_date_notice = False
                continue
            days = (fields.Date.from_string(rec.installation_order_date) - fields.Date.from_string(rec.date)).days
            if days > 0:
                rec.installation_date_notice = _('أُنشئ أمر التركيب بعد موعد الحجز بـ %s يوم.') % days
            elif days < 0:
                rec.installation_date_notice = _('أُنشئ أمر التركيب قبل موعد الحجز بـ %s يوم.') % abs(days)
            else:
                rec.installation_date_notice = _('تاريخ طلب أمر التركيب مطابق لتاريخ الحجز.')


    daily_capacity_view = fields.Integer(string='سعة اليوم', compute='_compute_daily_availability')
    daily_booked_view = fields.Integer(string='المحجوز اليوم', compute='_compute_daily_availability')
    daily_remaining_view = fields.Integer(string='المتبقي اليوم', compute='_compute_daily_availability')

    @api.model
    def _daily_occupied_appointments(self, branch_id, selected_day, now=None):
        """Bookings covering a real operating slot on the selected day.

        This is the same occupancy definition used by the calendar endpoint:
        active holds/confirmed/arrived bookings with a covered (date, slot).
        Each appointment is returned only once, irrespective of slot count.
        """
        # Odoo 13 Date fields can already be strings; normalize both inputs safely.
        selected_day = fields.Date.to_string(fields.Date.from_string(selected_day))
        now = now or fields.Datetime.now()
        candidates = self.search([
            ('branch_id', '=', branch_id),
            ('date', '<=', selected_day),
            '|', '&', ('end_date', '=', False), ('date', '>=', selected_day),
                 ('end_date', '>=', selected_day),
            ('state', 'in', ['provisional', 'contacting', 'confirmed', 'done', 'installation_created', 'postponed']),
        ])
        return candidates.filtered(
            lambda booking: booking.slot_id and booking._occupies(now)
            and any(day == selected_day for day, _slot in booking._covered_periods())
        )

    @api.depends('branch_id', 'date', 'end_date', 'slot_id', 'end_slot_id', 'state')
    def _compute_daily_availability(self):
        now = fields.Datetime.now()
        counts = {}
        for rec in self:
            rec.daily_capacity_view = rec.branch_id.capacity or 0
            rec.daily_booked_view = 0
            rec.daily_remaining_view = rec.daily_capacity_view
            if not rec.branch_id or not rec.date:
                continue
            selected_day = fields.Date.to_string(fields.Date.from_string(rec.date))
            key = (rec.branch_id.id, selected_day)
            if key not in counts:
                counts[key] = len(self._daily_occupied_appointments(
                    rec.branch_id.id, selected_day, now=now))
            rec.daily_booked_view = counts[key]
            rec.daily_remaining_view = max(0, rec.daily_capacity_view - counts[key])


    def _occupies(self, now=None):
        self.ensure_one()
        now = fields.Datetime.from_string(now or fields.Datetime.now())
        return self.state in ('confirmed','done','installation_created','postponed') or (self.state in ('provisional','contacting') and self.hold_until and fields.Datetime.from_string(self.hold_until) > now)

    def _booking_dates(self):
        self.ensure_one()
        first = fields.Date.from_string(self.date)
        last = fields.Date.from_string(self.end_date or self.date)
        if last < first:
            raise ValidationError(_('تاريخ نهاية الحجز لا يمكن أن يسبق تاريخ البداية.'))
        if (last - first).days > 365:
            raise ValidationError(_('الحد الأقصى للحجز سنة واحدة.'))
        return first, last

    def _covered_periods(self):
        """Return (date, slot) for every operating period occupied by this booking.

        An end slot is inclusive. Between dates, only configured working slots
        are counted; this allows overnight / multi-day work without requiring
        artificial midnight slots. Closed dates have no usable occupancy.
        """
        self.ensure_one()
        first, last = self._booking_dates()
        if not self.slot_id or self.slot_id.branch_id != self.branch_id:
            raise ValidationError(_('فترة البداية يجب أن تتبع الفرع.'))
        end_slot = self.end_slot_id or self.slot_id
        if end_slot.branch_id != self.branch_id:
            raise ValidationError(_('فترة النهاية يجب أن تتبع الفرع.'))
        if first == last and end_slot.start_hour < self.slot_id.start_hour:
            raise ValidationError(_('فترة النهاية يجب أن تأتي بعد فترة البداية.'))
        slots = self.env['ycc.slot'].search([
            ('branch_id', '=', self.branch_id.id), ('active', '=', True)
        ], order='start_hour,id')
        if self.slot_id not in slots or end_slot not in slots:
            raise ValidationError(_('فترة البداية أو النهاية غير مفعّلة.'))
        result = []
        current = first
        while current <= last:
            eligible = slots.filtered(lambda slot: slot.operates_on(current))
            if current == first:
                eligible = eligible.filtered(lambda slot: slot.start_hour >= self.slot_id.start_hour)
            if current == last:
                eligible = eligible.filtered(lambda slot: slot.start_hour <= end_slot.start_hour)
            for slot in eligible:
                result.append((fields.Date.to_string(current), slot))
            current += timedelta(days=1)
        if not result or result[0] != (fields.Date.to_string(first), self.slot_id) or result[-1] != (fields.Date.to_string(last), end_slot):
            raise ValidationError(_('فترة البداية أو النهاية غير متاحة في اليوم المحدد.'))
        # In a single day, preserve the old requirement for consecutive slots.
        if first == last:
            for (previous_day, previous), (following_day, following) in zip(result[:-1], result[1:]):
                if abs(previous.end_hour - following.start_hour) > 0.0001:
                    raise ValidationError(_('فترات الحجز في اليوم الواحد يجب أن تكون متتالية.'))
        return result

    def _covered_slots(self):
        """Compatibility with existing consumers; date-aware callers use periods."""
        self.ensure_one()
        return self.env['ycc.slot'].browse(list(dict.fromkeys(slot.id for _, slot in self._covered_periods())))

    def _check_capacity(self):
        # Serialize bookings per branch to avoid overlapping multi-day races.
        for rec in self.sorted(key=lambda r: (r.branch_id.id, r.id)):
            if not rec.branch_id or not rec.slot_id or not rec.date:
                continue
            self.env.cr.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', ['ycc:branch:%s' % rec.branch_id.id])
            periods = rec._covered_periods()
            if not rec._occupies():
                continue
            first, last = rec._booking_dates()
            others = self.search([
                ('branch_id', '=', rec.branch_id.id), ('id', '!=', rec.id),
                ('date', '<=', fields.Date.to_string(last)),
                '|', '&', ('end_date', '=', False), ('date', '>=', fields.Date.to_string(first)), ('end_date', '>=', fields.Date.to_string(first)),
                ('state', 'in', ['provisional', 'contacting', 'confirmed', 'done', 'installation_created', 'postponed'])
            ])
            now = fields.Datetime.now()
            occupied = {}
            for other in others:
                if other._occupies(now) and other.slot_id and other.date:
                    for day in set(day for day, _slot in other._covered_periods()):
                        occupied[day] = occupied.get(day, 0) + 1
            for day, slot in periods:
                if self.env['ycc.exception'].search_count([
                    ('branch_id', '=', rec.branch_id.id), ('date', '<=', day),
                    '|', '&', ('end_date', '=', False), ('date', '=', day), ('end_date', '>=', day),
                    '|', ('slot_id', '=', False), ('slot_id', '=', slot.id)
                ]):
                    raise ValidationError(_('إحدى الفترات المحددة مغلقة بسبب استثناء أو إجازة.'))
            for day in set(day for day, _slot in periods):
                if occupied.get(day, 0) >= rec.branch_id.capacity:
                    raise ValidationError(_('اكتملت القدرة الاستيعابية اليومية في %s: الحد الأقصى %s سيارات، بغض النظر عن عدد الفترات.') % (day, rec.branch_id.capacity))

    def _ycc_manager(self):
        return (self.env.user.has_group('yousentech_car_appointments.group_ycc_manager')
                or self.env.user.has_group('base.group_system'))

    def _ycc_arrival_only_user(self):
        return (not self._ycc_manager()
                and self.env.user.has_group('yousentech_car_appointments.group_ycc_sales_arrival'))

    def _ycc_can_book(self):
        return self._ycc_manager() or (not self._ycc_arrival_only_user()
            and self.env.user.has_group('yousentech_car_appointments.group_ycc_booking'))


    @api.model
    def create(self, vals):
        if not self._ycc_can_book():
            raise UserError(_('ليس لديك صلاحية إنشاء حجوزات جديدة.'))
        vals = dict(vals)
        vals['name'] = self.env['ir.sequence'].next_by_code('ycc.appointment') or 'New'
        if vals.get('state','provisional') in ('provisional','contacting') and vals.get('branch_id'):
            branch = self.env['ycc.branch'].browse(vals.get('branch_id'))
            vals['hold_until'] = fields.Datetime.to_string(fields.Datetime.from_string(fields.Datetime.now())+timedelta(minutes=branch.provisional_minutes or 120))
        rec = super().create(vals)
        rec._check_capacity()
        return rec

    def write(self, vals):
        vals = dict(vals)
        if not self._ycc_can_book() and not self._ycc_arrival_only_user():
            raise UserError(_('المواعيد للقراءة فقط؛ لا تملك صلاحية التعديل.'))
        if self._ycc_arrival_only_user():
            # This group can only mark an existing confirmed booking as arrived.
            # Linking the new installation order is handled by the order create hook.
            allowed_arrival = (set(vals) in ({'state'}, {'state', 'actual_arrival_at'}) and vals.get('state') == 'done'
                               and all(r.state == 'confirmed' for r in self))
            allowed_link = (set(vals) == {'installation_order_id', 'state'} and vals.get('state') == 'installation_created'
                            and all(r.state == 'done' and not r.installation_order_id for r in self)
                            and self.env.context.get('ycc_source_appointment_id'))
            if not (allowed_arrival or allowed_link):
                raise UserError(_('صلاحيتك تقتصر على وصول السيارة وإنشاء أمر تركيب.'))
        if 'hold_until' in vals and not (self.env.user.has_group('base.group_system') or self.env.context.get('ycc_internal_postpone')):
            raise UserError(_('Only administrators may edit hold expiry.'))
        if vals.get('state') in ('provisional','contacting') and 'hold_until' not in vals:
            for rec in self:
                if rec.state not in ('provisional','contacting','postponed') or not rec._occupies():
                    raise UserError(_('Expired holds cannot be reopened. Create a new booking.'))
        if 'state' in vals and vals['state'] in ('confirmed', 'done', 'installation_created'):
            for rec in self:
                if rec.state in ('expired', 'cancelled', 'no_show'):
                    raise UserError(_('Closed appointments cannot be reopened.'))
        result = super().write(vals)
        if set(vals) & {'branch_id','slot_id','end_slot_id','date','end_date','state','hold_until'}:
            self._check_capacity()
        return result

    def unlink(self):
        if not self._ycc_manager():
            raise UserError(_('حذف الحجوزات متاح لمدير المواعيد فقط.'))
        return super().unlink()

    @api.model
    def forecast_delivery_load(self, branch_id, target_date):
        """Read-only forecast by customer identity, never by license plate.

        A shared customer can own multiple cars; distinct work orders remain
        separate and are flagged for manual review instead of being merged.
        """
        if not branch_id or not target_date:
            return {'status': 'missing', 'message': 'حدد الفرع والتاريخ أولاً للتحقق.'}
        branch = self.env['ycc.branch'].browse(int(branch_id)).exists()
        if not branch:
            return {'status': 'missing', 'message': 'تهيئة الفرع غير متاحة.'}
        day = fields.Date.to_string(fields.Date.from_string(target_date))
        existing = self.search([('branch_id', '=', branch.id), ('date', '<=', day),
                                '|', '&', ('end_date', '=', False), ('date', '=', day),
                                ('end_date', '>=', day), ('state', 'in', ['done', 'installation_created'])])
        arrived = existing.filtered(lambda rec: rec.slot_id and rec._occupies() and
                                    any(d == day for d, slot in rec._covered_periods()))
        model_name = 'wo.installation.order.mst'
        if model_name not in self.env:
            return {'status': 'unconfigured', 'message': 'موديول أوامر التركيب غير متاح في قاعدة البيانات.'}
        Order = self.env[model_name]
        needed = ('delivery_date', 'delivery_period', 'order_date', 'state', 'branch_id', 'partner_id')
        if any(field not in Order._fields for field in needed):
            return {'status': 'unconfigured', 'message': 'حقول أوامر التركيب في النسخة المثبتة غير متوافقة.'}
        active_states = ['confirm', 'under_checking', 'work_order', 'execute_request',
                         'execute_started', 'return_to_modify']
        # The selected calendar date must fall within the order's expected
        # stay: order_date <= day <= delivery_date. Old overdue orders are
        # displayed separately, not counted as present for this day.
        common = [('branch_id', '=', branch.branch_id.id),
                  ('state', 'in', active_states), ('order_date', '<=', day)]
        current_orders = Order.search(common + [('delivery_date', '>=', day)], order='delivery_date asc, id asc')
        def customer_key(partner):
            return ' '.join((partner.name or '').split()).casefold() if partner else ''

        arrived_by_customer = {}
        for appt in arrived:
            key = customer_key(appt.partner_id)
            if key:
                arrived_by_customer.setdefault(key, []).append(appt)

        def item_for(order, status):
            key = customer_key(order.partner_id)
            delivery = fields.Date.to_string(order.delivery_date) if order.delivery_date else False
            return {'customer': order.partner_id.name if order.partner_id else 'عميل غير محدد',
                    'order': order.display_name, 'delivery_date': delivery or 'غير محدد',
                    'delivery_period': order.delivery_period.display_name if order.delivery_period else 'غير محددة',
                    'status': status, 'matched_appointment': bool(key and key in arrived_by_customer)}

        today_orders = current_orders.filtered(lambda o: fields.Date.to_string(o.delivery_date) == day)
        later_orders = current_orders - today_orders
        items = [item_for(o, 'موعد التسليم اليوم') for o in today_orders]
        later_items = [item_for(o, 'موعد التسليم لاحقاً') for o in later_orders]
        groups = {}
        for order in current_orders:
            key = customer_key(order.partner_id)
            if key:
                groups.setdefault(key, []).append(order)
        multiple_customers = sorted({group[0].partner_id.name for group in groups.values()
                                     if len(group) > 1 and group[0].partner_id})
        matched_keys = set(groups) & set(arrived_by_customer)
        summary = ('تاريخ الفحص: %s | موعد التسليم اليوم: %s | '
                   'موعد التسليم لاحقاً: %s | حجوزات وصلت: %s | '
                   'عملاء متطابقون بالاسم: %s. '
                   'المطابقة باسم العميل فقط، والنتيجة تقديرية ولا تؤكد وجود السيارة فعلياً.') % (
                       day, len(items), len(later_items), len(arrived), len(matched_keys))
        return {'status': 'ok', 'date': day, 'capacity': branch.capacity,
                'pending_orders': len(items), 'arrived': len(arrived),
                'matched_customers': len(matched_keys),
                'multiple_customers': multiple_customers, 'orders': items,
                'later_orders': later_items, 'today_count': len(items),
                'later_count': len(later_items), 'message': summary}

    def action_open_installation_wizard(self):
        self.ensure_one()
        if not (self._ycc_can_book() or self._ycc_arrival_only_user()):
            raise UserError(_('لا تملك صلاحية إنشاء أمر تركيب.'))
        if self.state != 'done':
            raise UserError(_('يجب تسجيل وصول السيارة أولاً.'))
        if self.installation_order_id:
            return self.action_open_installation_order()
        if not self.branch_id or not self.branch_id.branch_id:
            raise UserError(_('يجب تحديد الفرع قبل إنشاء أمر التركيب.'))
        # Use the real installation order model and its own native fields.
        # No duplicate transient wizard/header is maintained.
        branch = self.branch_id.branch_id
        return {
            'type': 'ir.actions.act_window',
            'name': _('إنشاء أمر تركيب — بيانات الهيدر'),
            'res_model': 'wo.installation.order.mst',
            'view_mode': 'form',
            'views': [(self.env.ref('yousentech_car_appointments.view_ycc_native_installation_header').id, 'form')],
            'target': 'new',
            'context': dict(self.env.context,
                ycc_source_appointment_id=self.id,
                default_partner_id=self.partner_id.id,
                default_partner_mobile=self.phone or self.partner_id.mobile or '',
                default_branch_id=branch.id,
                default_company_id=self.company_id.id or self.env.company.id,
                default_order_date=fields.Date.context_today(self),
                default_ycc_appointment_id=self.id,
                default_car_manuf_id=self.car_manuf_id.id or False,
                default_agency_id=self.agency_id.id or False,
                default_car_type_id=self.car_type_id.id or False,
                default_car_panel_no=self.vehicle_plate or False,
                default_delivery_date=self.end_date or self.date or False,
                default_state='draft'),
        }

    def action_open_installation_order(self):
        self.ensure_one()
        if not self.installation_order_id:
            raise UserError(_('لم يتم إنشاء أمر تركيب لهذا الحجز بعد.'))
        return {
            'type': 'ir.actions.act_window', 'name': _('أمر التركيب'),
            'res_model': 'wo.installation.order.mst',
            'res_id': self.installation_order_id.id,
            'views': [(self.env.ref('qimamhd_wo_v3.wo_installation_order_view').id, 'form')],
            'view_mode': 'form', 'target': 'current',
        }

    def action_forecast_delivery_load(self):
        if self._ycc_arrival_only_user():
            raise UserError(_('هذا الإجراء غير متاح لمندوب الوصول.'))
        self.ensure_one()
        result = self.forecast_delivery_load(self.branch_id.id, self.date)
        from markupsafe import escape
        def safe(value):
            return str(escape(str(value or '')))
        def rows(items):
            return ''.join('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>' % (
                safe(item['customer']), safe(item['order']),
                safe(item['delivery_date']) + ' · ' + safe(item['delivery_period']),
                safe(item['status'])) for item in items)
        table_head = '<table class="table table-sm table-striped"><thead><tr><th>العميل</th><th>أمر التركيب</th><th>موعد التسليم · فترة التسليم</th><th>الحالة</th></tr></thead><tbody>'
        body = '<div dir="rtl" style="line-height:1.9"><p>%s</p>' % safe(result.get('message'))
        if result.get('status') == 'ok':
            body += '<div style="background:#f0f7ff;border:1px solid #c9dcf5;border-radius:10px;padding:12px"><h4>موعد التسليم في اليوم المحدد (%s)</h4>' % result['today_count']
            body += table_head + rows(result['orders']) + '</tbody></table>' if result['orders'] else '<p>لا توجد أوامر موعد تسليمها في هذا اليوم.</p>'
            body += '</div>'
            if result['later_count']:
                body += '<details style="margin-top:10px"><summary>موعد التسليم لاحقاً (%s) — عرض التفاصيل</summary>' % result['later_count']
                body += table_head + rows(result['later_orders']) + '</tbody></table></details>'
        body += '</div>'
        wizard = self.env['ycc.forecast.wizard'].create({'details': body})
        return {'type': 'ir.actions.act_window', 'name': 'التحقق من السيارات الموجودة',
                'res_model': 'ycc.forecast.wizard', 'res_id': wizard.id,
                'view_mode': 'form', 'views': [(False, 'form')], 'target': 'new'}

    def action_open_contact_wizard(self):
        if self._ycc_arrival_only_user():
            raise UserError(_('هذا الإجراء غير متاح لمندوب الوصول.'))
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'إضافة سجل تواصل',
            'res_model': 'ycc.contact.wizard',
            'view_mode': 'form',
            'views': [(self.env.ref('yousentech_car_appointments.view_ycc_contact_wizard_form').id, 'form')],
            'target': 'new',
            'context': {'default_appointment_id': self.id},
        }

    def action_contacting(self): self.write({'state':'contacting'})
    def action_confirm(self):
        if self._ycc_arrival_only_user():
            raise UserError(_('هذا الإجراء غير متاح لمندوب الوصول.'))
        for rec in self:
            if rec.state not in ('provisional','contacting','postponed') or not rec._occupies():
                raise UserError(_('Only active provisional bookings can be confirmed.'))
            rec.write({'state':'confirmed'})
    def action_cancel(self): self.write({'state':'cancelled'})
    def action_done(self):
        for rec in self:
            if rec.state != 'confirmed':
                raise UserError(_('يجب تأكيد الموعد قبل تسجيل وصول السيارة.'))
            arrival = fields.Datetime.now()
            rec.write({'state': 'done', 'actual_arrival_at': arrival})
            rec.message_post(body=_('تم تسجيل وصول السيارة الفعلي في %s بواسطة %s. تاريخ الحجز المخطط: %s.') % (arrival, self.env.user.name, rec.date or '-'))
    def action_open_postpone(self):
        self.ensure_one()
        if self.state not in ('provisional','contacting','confirmed','postponed'):
            raise UserError(_('لا يمكن تأجيل هذا الحجز بعد وصول السيارة أو إغلاقه.'))
        return {'type':'ir.actions.act_window', 'name':_('تأجيل الموعد'),
                'res_model':'ycc.postpone.wizard', 'view_mode':'form', 'target':'new',
                'context':dict(self.env.context, default_appointment_id=self.id,
                               default_new_date=self.date,
                               default_new_slot_id=self.slot_id.id)}

    def action_no_show(self): self.write({'state':'no_show'})

    @api.model
    def cron_expire_holds(self):
        self.search([('state','in',['provisional','contacting']),('hold_until','!=',False),('hold_until','<=',fields.Datetime.now())]).write({'state':'expired'})

class YCCContactWizard(models.TransientModel):
    _name = 'ycc.contact.wizard'
    _description = 'إضافة سجل تواصل'

    appointment_id = fields.Many2one('ycc.appointment', string='الحجز', required=True, readonly=True)
    contact_at = fields.Datetime(string='تاريخ ووقت التواصل', required=True, default=fields.Datetime.now)
    user_id = fields.Many2one('res.users', string='المندوب', required=True, default=lambda self: self.env.user)
    channel = fields.Selection([('call','اتصال'),('whatsapp','واتساب'),('sms','رسالة'),('other','أخرى')], string='وسيلة التواصل', required=True, default='call')
    result = fields.Selection([('no_answer','لم يرد'),('follow_up','متابعة'),('reschedule','تغيير موعد'),('confirmed','تأكيد'),('other','أخرى')], string='نتيجة التواصل', required=True, default='follow_up')
    note = fields.Text(string='تفاصيل التواصل', required=True)
    next_contact_at = fields.Datetime(string='موعد المتابعة القادمة')

    def action_save_contact(self):
        self.ensure_one()
        appointment = self.appointment_id
        appointment.check_access_rights('write')
        appointment.check_access_rule('write')
        self.env['ycc.contact'].create({
            'appointment_id': appointment.id,
            'contact_at': self.contact_at,
            'user_id': self.user_id.id,
            'channel': self.channel,
            'result': self.result,
            'note': self.note,
            'next_contact_at': self.next_contact_at,
        })
        appointment.write({'next_contact_at': self.next_contact_at or False})
        return {'type': 'ir.actions.act_window_close'}


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


class YCCForecastWizard(models.TransientModel):
    _name = 'ycc.forecast.wizard'
    _description = 'ملخص التحقق من السيارات الموجودة'
    details = fields.Html(string='ملخص الإشغال', readonly=True, sanitize=True)


class YCCPostponeWizard(models.TransientModel):
    _name = 'ycc.postpone.wizard'
    _description = 'تأجيل موعد حجز السيارة'
    appointment_id = fields.Many2one('ycc.appointment', required=True, readonly=True)
    new_date = fields.Date(string='تاريخ الحجز الجديد', required=True)
    new_end_date = fields.Date(string='تاريخ نهاية الحجز الجديد')
    new_slot_id = fields.Many2one('ycc.slot', string='الفترة الجديدة', required=True)
    reason = fields.Text(string='سبب التأجيل', required=True)

    def action_apply(self):
        self.ensure_one()
        rec = self.appointment_id
        if not rec._ycc_can_book():
            raise UserError(_('ليس لديك صلاحية تأجيل الحجوزات.'))
        if rec.state not in ('provisional','contacting','confirmed','postponed'):
            raise UserError(_('لا يمكن تأجيل حجز وصل بالفعل أو أُغلق.'))
        if self.new_slot_id.branch_id != rec.branch_id:
            raise ValidationError(_('الفترة المختارة لا تتبع فرع الحجز.'))
        # Postponement selects one new day; the end date is automatically the same day.
        new_end_date = self.new_date
        if (self.new_date == rec.date and new_end_date == (rec.end_date or rec.date)
                and self.new_slot_id == rec.slot_id):
            raise ValidationError(_('يجب اختيار تاريخ أو فترة مختلفة عن الموعد الحالي.'))
        old_date = rec.date
        old_end = rec.end_date or rec.date
        old_slot = rec.slot_id.display_name
        # A postponed appointment is a NEW provisional booking, not a separate
        # operational state. Renew its hold so the booking can be confirmed.
        expiry = fields.Datetime.to_string(
            fields.Datetime.from_string(fields.Datetime.now()) +
            timedelta(minutes=rec.branch_id.provisional_minutes or 120))
        rec.with_context(ycc_internal_postpone=True).write({
            'date': self.new_date, 'end_date': new_end_date,
            'slot_id': self.new_slot_id.id, 'end_slot_id': False,
            'state': 'provisional', 'hold_until': expiry,
            'was_postponed': True, 'postponement_count': rec.postponement_count + 1,
        })
        rec.message_post(body=_(
            'تأجيل موعد الحجز: من %s إلى %s (نهاية الموعد السابق: %s، الفترة السابقة: %s، '
            'الفترة الجديدة: %s). السبب: %s. بواسطة: %s. الحالة الجديدة: حجز مبدئي بانتظار التأكيد.') %
            (old_date, self.new_date, old_end, old_slot,
             self.new_slot_id.display_name, self.reason, self.env.user.name))
        return {'type':'ir.actions.act_window_close'}
