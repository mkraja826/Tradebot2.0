# Remote administration design — not installed

The existing local approval executor remains authoritative. Chat messages and MCP request records alone are not authentication credentials.

Proposed deployment: an independently provisioned operator-controlled agent, separate from the MCP identity and trading services. Authenticate operator approval using a trusted identity provider or protected deployment environment. Bind each approval to the exact request ID, canonical argument digest, target environment, expiry and approved revision. Reject replay, expired approvals and changed arguments. Maintain durable execution receipts and audit records. Fail closed when identity or policy cannot be verified.

Initial scope: read-only QA snapshot refresh and Admin MCP release deployment only. Trading service changes, broker access, credential reads, arbitrary shell and destructive actions are excluded. Require separate authorization for any scope expansion. Verify tests, release digest and rollback target before deployment.

Bootstrap requires an existing authorized VM management channel or a one-time operator installation. GitHub repository access does not establish VM authority. Do not install a privileged runner through the existing request queue or weaken local approval. No live deployment is authorized by this document.
