#!/usr/bin/env bash
# Run in Google Cloud Shell, authenticated as the project's administrator.
# Creates identities, three EMPTY secret containers and least-privilege IAM.
# This script never reads, copies or prints trading API credentials.
set -euo pipefail
set +x

PROJECT_ID="$(gcloud config get-value project 2>/dev/null)"
if [[ ! "$PROJECT_ID" =~ ^[a-z][a-z0-9-]{4,61}[a-z0-9]$ ]]; then
  echo "Select your intended Google Cloud project with gcloud config set project YOUR_PROJECT_ID"
  exit 1
fi

REPO="mkraja826/Tradebot2.0"
POOL="tradebot-github"
PROVIDER="repo-main-sync"
SYNC_ACCOUNT_ID="tradebot-gh-sync"
VM_ACCOUNT_ID="tradebot-vm"
SYNC_SA="$SYNC_ACCOUNT_ID@$PROJECT_ID.iam.gserviceaccount.com"
VM_SA="$VM_ACCOUNT_ID@$PROJECT_ID.iam.gserviceaccount.com"
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
if [[ ! "$PROJECT_NUMBER" =~ ^[0-9]+$ ]]; then
  echo "Unable to read Google Cloud project number."
  exit 1
fi

echo "Setting up Secret Manager and narrow GitHub OIDC trust for project: $PROJECT_ID"
gcloud services enable iam.googleapis.com iamcredentials.googleapis.com \
  sts.googleapis.com secretmanager.googleapis.com \
  --project="$PROJECT_ID" --quiet

if ! gcloud iam service-accounts describe "$SYNC_SA" --project="$PROJECT_ID" >/dev/null 2>&1; then
  gcloud iam service-accounts create "$SYNC_ACCOUNT_ID" \
    --display-name="Tradebot GitHub secret-version writer" \
    --project="$PROJECT_ID" --quiet
fi
if ! gcloud iam service-accounts describe "$VM_SA" --project="$PROJECT_ID" >/dev/null 2>&1; then
  gcloud iam service-accounts create "$VM_ACCOUNT_ID" \
    --display-name="Tradebot VM Secret Manager reader" \
    --project="$PROJECT_ID" --quiet
fi

if ! gcloud iam workload-identity-pools describe "$POOL" --location=global --project="$PROJECT_ID" >/dev/null 2>&1; then
  gcloud iam workload-identity-pools create "$POOL" \
    --location=global --display-name="Tradebot GitHub OIDC" \
    --project="$PROJECT_ID" --quiet
fi

# Trust only the exact manual secret-sync workflow on this repo's main.
CONDITION="assertion.repository == '$REPO' && assertion.ref == 'refs/heads/main' && assertion.event_name == 'workflow_dispatch' && assertion.workflow_ref == '$REPO/.github/workflows/sync-gcp-secrets.yml@refs/heads/main'"
if ! gcloud iam workload-identity-pools providers describe "$PROVIDER" \
  --workload-identity-pool="$POOL" --location=global \
  --project="$PROJECT_ID" >/dev/null 2>&1; then
  gcloud iam workload-identity-pools providers create-oidc "$PROVIDER" \
    --workload-identity-pool="$POOL" --location=global \
    --issuer-uri="https://token.actions.githubusercontent.com" \
    --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
    --attribute-condition="$CONDITION" \
    --project="$PROJECT_ID" --quiet
else
  ACTUAL="$(gcloud iam workload-identity-pools providers describe "$PROVIDER" \
    --workload-identity-pool="$POOL" --location=global \
    --format='value(attributeCondition)' --project="$PROJECT_ID")"
  if [[ "$ACTUAL" != "$CONDITION" ]]; then
    echo "Existing OIDC provider has a different trust policy. Refusing to use it."
    exit 1
  fi
fi

POOL_PRINCIPAL="principalSet://iam.googleapis.com/projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/$POOL/attribute.repository/$REPO"
gcloud iam service-accounts add-iam-policy-binding "$SYNC_SA" \
  --member="$POOL_PRINCIPAL" --role="roles/iam.workloadIdentityUser" \
  --project="$PROJECT_ID" --quiet >/dev/null

for SECRET_ID in tradebot-delta-demo-api-key tradebot-delta-demo-api-secret tradebot-tb-api-key; do
  if ! gcloud secrets describe "$SECRET_ID" --project="$PROJECT_ID" >/dev/null 2>&1; then
    gcloud secrets create "$SECRET_ID" --replication-policy=automatic \
      --project="$PROJECT_ID" --quiet >/dev/null
  fi

  # GitHub can ADD a version but cannot read secret payloads.
  gcloud secrets add-iam-policy-binding "$SECRET_ID" \
    --member="serviceAccount:$SYNC_SA" \
    --role="roles/secretmanager.secretVersionAdder" \
    --project="$PROJECT_ID" --quiet >/dev/null

  # VM can READ only these secrets, not add/change versions.
  gcloud secrets add-iam-policy-binding "$SECRET_ID" \
    --member="serviceAccount:$VM_SA" \
    --role="roles/secretmanager.secretAccessor" \
    --project="$PROJECT_ID" --quiet >/dev/null
done

cat <<EOF

SUCCESS: Trust and three EMPTY secret containers configured.
No trading credentials have been transferred yet.

Create the following GitHub repository VARIABLES (not Secrets):
GCP_PROJECT_ID = $PROJECT_ID
GCP_WIF_PROVIDER = projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/$POOL/providers/$PROVIDER
GCP_SYNC_SERVICE_ACCOUNT = $SYNC_SA

VM service account to attach in Compute Engine:
$VM_SA

Manually run "Sync GitHub secrets to GCP Secret Manager (manual only)" on GitHub.
IMPORTANT: Confirm your VM external IPv4 is STATIC before stopping the VM.
EOF
