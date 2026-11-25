# Cloud preview deployment
Run the two independent market preview workers and local-only dashboard under
the dedicated recovertrading system user. The preview does not request paid AI
or submit orders. Install the two systemd unit files after checking out a pinned
revision into /opt/recover-trading/current and creating the writable directory
/var/lib/recover-trading/preview owned by recovertrading. Start
recover-preview@BTCUSD.service, recover-preview@XAUTUSD.service and
recover-dashboard.service. Dashboard port 18766 is separate from the legacy
services and should be accessed via SSH forwarding, not exposed publicly.
The existing trading services and their controls are not replaced by this
preview. Authenticated demo integration and secure dashboard routing remain
separate steps.
