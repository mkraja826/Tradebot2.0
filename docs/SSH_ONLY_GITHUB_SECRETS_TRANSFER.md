# Transfer existing GitHub Actions demo secrets to the VM (no Cloud Shell)

This workflow is **prepared but not yet run**. Do not confuse it with the separate Google Cloud Secret Manager workflow. This route uses only **VM SSH + GitHub Actions**. It does not require retyping existing Delta demo or Top Billing credentials and does not need Google Cloud IAM configuration.

## Security design

1. The Iowa VM generates a one-time X25519 private/public keypair. **The private key never leaves the VM.**
2. The user shares only the compact public key starting `tbx1:`. The assistant commits that public key to `ops/recipient-public-key.txt`.
3. A manually launched GitHub Action encrypts **exactly three existing Actions secrets** (`DELTA_DEMO_API_KEY`, `DELTA_DEMO_API_SECRET`, `TB_API_KEY`) with an ephemeral X25519 key, HKDF-SHA256 and AES-256-GCM.
4. GitHub commits the resulting **encrypted ciphertext only** to `ops/sealed/tradebot-demo-credentials.enc.json`. **This repository is public, so the ciphertext and its history will be public.** The secret values are not included in the file or in logs. Anyone who later obtains the VM's private transfer key *before it is deleted* could decrypt the public ciphertext; protect VM SSH access.
5. The VM pulls the encrypted file, decrypts to `~/.config/tradebot2/keys.env` with mode 0600 and removes its one-time transfer private key after successful import. No trading is started.
6. The local `keys.env` is **plaintext to the VM user and root** (required by the existing bot), and must not be committed, printed or shared. Restrict VM access.

The manual workflow has `contents: write` only to commit the encrypted package and uses no Google Cloud permissions or service-account keys.

## Step 1 — VM SSH (user)

Open Compute Engine → VM instances → **SSH** on the Iowa VM. In the existing Tradebot project folder run:

```bash
cd ~/Tradebot2.0
git pull --ff-only
source .venv/bin/activate
python -m pip install -e .
python -m tradebot.sealed_transfer generate
```

Expected output includes **one short line** of this form:

```text
tbx1:XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
```

**Only send that `tbx1:` public key to the assistant.** It is safe to share. Never send `~/.config/tradebot2/transfer-x25519.key`, `keys.env`, API credentials or screenshots showing them.

If run again before import, `generate` reprints the **same public key** instead of replacing the private key.

## Step 2 — Configure the public recipient (assistant)

The assistant creates the repository file `ops/recipient-public-key.txt` using the `tbx1:` public key supplied by the user. No private secrets are written to the repository. Do not proceed until that file exists and its value matches your VM.

## Step 3 — Launch GitHub Action (user)

Open:

https://github.com/mkraja826/Tradebot2.0/actions/workflows/sealed-demo-credentials.yml

Choose **Run workflow → main → Run workflow** and wait for the green success indication.

This uses the three existing GitHub repository secrets. It will create a public **encrypted** commit. Only GitHub Actions reads the plaintext credentials during the job. This workflow does not call Delta or Top Billing.

If `git push` fails due to a repository rule, don't disable protection. Ask the assistant for an alternative encrypted artifact delivery.

## Step 4 — Import on the VM and verify (user)

In VM SSH run:

```bash
cd ~/Tradebot2.0
git pull --ff-only
source .venv/bin/activate
python -m tradebot.sealed_transfer import
```

Expected:

```text
SUCCESS: Three credentials saved to ~/.config/tradebot2/keys.env (0600).
The one-time VM decryption key was removed.
Demo order execution is disabled. No trades or paid AI calls made.
```

Then authenticated READ ONLY verification:

```bash
source ~/.config/tradebot2/keys.env
python -m tradebot.delta_probe --authenticated
tradebot ai-check
```

**Stop if** Delta says `IP_NOT_WHITELISTED`, and confirm the static VM IPv4 matches the demo key whitelist. Do not turn off IP restrictions or paste API keys into chat.

## Current limitations

This is a quick bootstrap, not managed automatic rotation. The public encrypted package remains in Git history (even after deleting the file), but the **one-time decryption private key is removed after import**. Store local credentials only in the restrictive environment file. If the VM or existing keys may have been compromised, rotate those keys at their providers and perform a new secure transfer.

Neither successful transfer nor an authenticated GET establishes that Delta multi-leg demo orders, forced closeouts or unattended operation are safe. **Keep `ENABLE_DEMO_ORDERS=false`** and do not launch unattended execution.
