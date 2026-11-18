# Tradebot 2.0: Move GitHub API secrets to Google Cloud

**Current status:** Implementation is committed, **not yet provisioned or transferred**. This requires a one-time action in your Google Cloud project and three repository **Variables**. Neither bot orders nor paid AI requests are involved.

## What this does

GitHub Actions encrypted secrets (`DELTA_DEMO_API_KEY`, `DELTA_DEMO_API_SECRET`, `TB_API_KEY`) are sent to **three specific Google Cloud Secret Manager secrets**, by a **manually started** Actions workflow. The workflow authenticates to Google Cloud using short-lived OpenID Connect (OIDC) tokens and Workload Identity Federation, **not** an exported Google service-account JSON key.

The GitHub identity can **only add new versions** to those three secrets. A separate service account, `tradebot-vm`, can **only read** those same three secrets. The VM retrieves them via its metadata server and keeps them only in the launched process environment. This does not create a permanent service or enable trading.

The workflow won't run until Google Cloud IAM is configured and you manually press **Run workflow**. GitHub repository secrets are not readable after creation: Actions only receives values while the job runs.

## Step 1 — One-time Google Cloud setup (Cloud Shell, NOT VM SSH)

In the Google Cloud Console, verify you have selected the **same Google Cloud project** that owns your Iowa VM. Use the upper-right **Activate Cloud Shell** terminal.

Run:

```bash
git clone https://github.com/mkraja826/Tradebot2.0.git
cd Tradebot2.0
gcloud config get-value project
bash ops/bootstrap_gcp_identity.sh
```

If the displayed project ID is not the one containing your VM, correct it first with `gcloud config set project YOUR_PROJECT_ID`; then run the script.

The bootstrap script enables the IAM, IAM Credentials, STS and Secret Manager APIs; creates two dedicated service accounts, a narrowly restricted GitHub Workload Identity Federation provider, and **three empty secrets**. It grants only these roles:

- `tradebot-gh-sync`: `roles/secretmanager.secretVersionAdder` **on each of the three secrets** plus repository-restricted `roles/iam.workloadIdentityUser` on its own service account.
- `tradebot-vm`: `roles/secretmanager.secretAccessor` **on the same three secrets only**.

The GitHub trust provider accepts only `mkraja826/Tradebot2.0`, branch `main`, event `workflow_dispatch`, and the exact `sync-gcp-secrets.yml` workflow. No permissions are given to GitHub to inspect the VM or any other secrets. The bootstrap script prints no credentials.

**Important:** The Cloud Shell account must have permissions to create identities and secrets and manage IAM policies. If it fails, stop and share only the error message with credentials redacted; do not grant broad Owner or Editor roles to the bot's new service accounts.

## Step 2 — Add GitHub Actions repository Variables (not Secrets)

Open:

https://github.com/mkraja826/Tradebot2.0/settings/variables/actions

Under **Repository variables**, add the exact three names printed by the Cloud Shell bootstrap script:

- `GCP_PROJECT_ID` — the Google Cloud project ID.
- `GCP_WIF_PROVIDER` — the full provider path starting with `projects/PROJECT_NUMBER/locations/global/...`.
- `GCP_SYNC_SERVICE_ACCOUNT` — the `tradebot-gh-sync@PROJECT_ID.iam.gserviceaccount.com` email.

These are identifiers, **not** secret key values. Leave the three existing GitHub **Secrets** intact.

## Step 3 — Run the transfer ONCE

Open:

https://github.com/mkraja826/Tradebot2.0/actions/workflows/sync-gcp-secrets.yml

Choose **Run workflow → main → Run workflow**. This will add a new version to each of these secret containers:

- `tradebot-delta-demo-api-key`
- `tradebot-delta-demo-api-secret`
- `tradebot-tb-api-key`

The workflow reads the existing three GitHub secrets securely, sends them through TLS to Secret Manager via stdin (not command-line arguments or repository files), and prints only success/failure. **Do not rerun unnecessarily** because each run creates additional billable secret versions.

Check Google Cloud Secret Manager: https://console.cloud.google.com/security/secret-manager

Each of the three secrets should now have an enabled version. Do not open or screenshot the secret values.

## Step 4 — Attach the reader service account to the existing VM

Your VM in earlier screenshots was `instance-20261118-085544` in `us-central1-f`. Before stopping it, **verify your external IPv4 was promoted to static**; stopping an instance can release an ephemeral address, invalidating Delta's API whitelist.

Go to Compute Engine → VM instances:

https://console.cloud.google.com/compute/instances

Stop the Iowa VM, open **Edit**, and under **Identity and API access** select:

- **Service account:** `tradebot-vm@YOUR_PROJECT_ID.iam.gserviceaccount.com`
- **Access scopes:** **Allow full access to all Cloud APIs** (`cloud-platform`). The service account's narrowly limited IAM roles still determine which resources are accessible.

Save, restart the VM, and verify the external IP still matches your Delta **demo** key's allowlist. Don't switch to a live exchange API key.

**Security note:** Processes with access to the VM's metadata service can obtain the VM identity's token; users with control over that VM can potentially access its allowed secrets. Secure SSH access, avoid sharing the VM, and never grant this VM broad project roles.

## Step 5 — Verify Delta demo from the VM with zero order permissions

SSH into the Iowa VM (not Cloud Shell) and run:

```bash
cd ~/Tradebot2.0
git pull --ff-only
source .venv/bin/activate

# Fetches secrets from GCP into this command's process environment only.
python -m tradebot.gcp_runtime -- python -m tradebot.delta_probe --authenticated
```

Expected evidence: `"authenticated_read": "passed"`, valid wallet, order and position schemas and `"orders_submitted": false`. The wrapper **forces** `ENABLE_DEMO_ORDERS=false`. It does not create an environment file, launch continuous trading or send a paid model request.

To check the AI model catalogue without a paid completion:

```bash
python -m tradebot.gcp_runtime -- tradebot ai-check
```

Never paste or screenshot secret values. If it fails, share only its sanitized error message.

## Costs and maintenance

Google Cloud can charge for active secret versions and Secret Manager access operations. The GitHub-to-GCP sync is manual, not scheduled, and the VM fetches secrets once when starting a command; don't repeatedly fetch each minute. Keep an eye on Cloud Billing and budgets. Updating a secret in GitHub later does **not** automatically update Secret Manager; rerun the sync workflow manually after planned rotations.

The authenticated check verifies only GET endpoint schemas. Before enabling autonomous demo orders, complete supervised exchange integration, real-time position reconciliation, verified order/closeout paths, watchdogs, and emergency alerts.
