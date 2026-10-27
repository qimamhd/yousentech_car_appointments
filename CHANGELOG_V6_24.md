# V6.24 - Postponement workflow
- Rescheduling sets the operational state to `provisional` and renews the hold.
- `was_postponed` and `postponement_count` persist after confirmation.
- Calendar and booking modal show a separate orange postponed badge.
- Chatter records old/new date, time slot, reason and user.
- Existing arrival and installation-order creation workflows remain unchanged.
- Requires Odoo module upgrade for new stored fields.
