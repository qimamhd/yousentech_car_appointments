# V6.60 – Booking workflow enhancements

- Added manager-only visibility for optional booking end date and end period.
- Added a daily calendar mode alongside weekly and monthly modes.
- Added server-side prevention of backdated bookings for non-managers.
- Booking records become read-only after an installation order is linked; deleting the linked order restores the booking to Confirmed.
- Invoice linking/creation is blocked until the installation order reaches the work-completed states already used by the appointment status computation.
- Added mandatory reasons for cancellation and no-show, stored on the appointment.
- Added configurable arrival-to-installation-order alert threshold and scheduled activity notification.
- Added a required-reason delivery-date change wizard and immutable history rows.
- Added independent check-only bookings using the existing appointment fields and daily branch capacity. The workflow is Confirmed → Arrived → Check Completed; it does not create an installation order and does not alter the existing installation-order check-date workflow.
- Existing installation-order check capacity and check-date rules are retained.
