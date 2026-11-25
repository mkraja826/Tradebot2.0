# Demo activation

Install recover-demo.service and create /var/lib/recover-trading/demo owned by
recovertrading. The owner configures /etc/recover-trading/demo.env locally,
using demo.env.example as the variable-name reference. Never expose credentials.
The service runs a read-only authenticated account/product preflight before
starting the existing demo execution loop. This verifies wallet reads and
distinct key configuration, not distinct account ownership or order compatibility.
No model request or order is issued by the preflight. The owner must verify the
intended demo accounts and exchange bracket behavior. Start only after the local
configuration and validation are complete. The existing preview and demo journals
are separate; point the read-only dashboard at the demo directory after activation.
The preview scanners can be stopped at activation to avoid duplicate data polling.
