# TB2.0 Admin MCP v1 — staged candidate

Separate from the running trading engine and the existing read-only MCP. This branch does not modify the trading runtime. Do not merge or deploy the base branch as part of installing this extension.

## Status

Twenty admin tool definitions: ten bounded read operations and ten local-approval request operations. **Only the cleanup request has a local executor in this increment.** The other nine mutation tools write requests but have no installed executor. They must not be presented as completed actions or enabled for unattended execution. No broker/order tools, arbitrary shell, sudo access from MCP, raw log reader, or secret/config file reader.

Read tools: server_health, disk_usage, list_files, read_file, service_status, service_logs, git_status, git_diff, database_inspect, audit_history.

Request tools: disk_cleanup, apply_patch, restart_service, git_commit, run_tests, deploy_version, install_dependency, database_backup, create_snapshot, rollback_version.

## Local test before any connection

Run on an isolated checkout, not the live trading tree:
```sh
python3 -m unittest discover -s admin_mcp -p 'test_*.py' -v
```

## VM setup (operator-controlled, not performed by this branch)

1. Check free disk space first. Do not clone into a full filesystem.
2. Inspect the existing MCP launcher's Python environment and active service names. Keep its current tunnel and trading units unchanged. Create a separate nonprivileged service identity, separate source-only checkout, and private request directory. The process must not be able to read broker secrets or modify the live checkout. Grant read access only to explicitly selected snapshot files and system telemetry; keep the request directory mode 0700. Do not grant generic journal, root, or docker group access.
3. Configure TB2_ADMIN_SOURCE, TB2_ADMIN_QUEUE, TB2_ADMIN_SNAPSHOTS and TB2_ADMIN_SERVICES (comma-separated exact service names). Leave services unset until verified. Ensure the separately installed Python MCP SDK supports FastMCP; pin a compatible version in the isolated environment. Install the reviewed admin file outside the trading tree, owned by the operator, and run `python /path/to/tb2_admin.py` as a stdio MCP process under the dedicated account.
4. Verify MCP initialize, tools/list (20 names), server_health, disk_usage and request-only behavior locally. Then create a separate authenticated app/tunnel binding for this stdio server. Do not replace the existing app registration or expose an unauthenticated public URL. ChatGPT write support and tunnel configuration must be checked against the actual account.
5. For the cleanup request, review approve_cleanup.py and install it as a root-owned non-writable executable; it uses the default queue path /var/lib/tb2-admin/requests. Execute locally as root with the exact pending request ID only after reading the request and authorizing archived journal retention of seven days. The fixed executor runs apt-get clean, journalctl --vacuum-time=7d and df before/after. It never restarts a trading service. Its completion is logged in the system journal. The request file itself is not a trusted completion record and remains pending in this version; verify disk usage and the root journal separately.
6. Implement and verify the remaining nine executors with explicit operator policy, exact service/checkout paths, demo-account isolation, backups, dry runs, bounded inputs, and rollback testing. Run tests/dependencies in a sandbox with no broker credentials. Deploy/rollback must use verified immutable revisions; GCP snapshot needs the correct project/disk and a narrowly scoped identity. No production account access. Never use a generic root command dispatcher or grant MCP blanket sudo.

The existing plugin uses an externally registered app ID; updating a plugin manifest cannot add tools to the VM. A new connector needs an actual deployed server and authenticated registration. No deployment or server modification is performed by this commit.
