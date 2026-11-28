import {authenticate} from "./approval_browser.js";

const id = new URLSearchParams(location.search).get("request");
const status = document.getElementById("status");
const button = document.getElementById("approve");
const details = document.getElementById("details");

async function call(action, body) {
  const response = await fetch("/admin/approvals/" + id + "/" + action, {
    method: "POST", credentials: "same-origin", redirect: "error", cache: "no-store",
    headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)
  });
  if (!response.ok) throw new Error("Approval request unavailable");
  return response.json();
}

async function review() {
  const {record, digest} = await call("review", {});
  for (const [label, value] of [
    ["Request", record.id], ["Service", record.target],
    ["Installed revision", record.expected_revision], ["Release to deploy", record.arguments.commit_sha]
  ]) {
    const term = document.createElement("dt");
    const item = document.createElement("dd");
    term.textContent = label;
    item.textContent = value;
    details.append(term, item);
  }
  details.hidden = false;
  button.hidden = false;
  status.textContent = "Review both revisions before approving.";
  button.onclick = async () => {
    button.disabled = true;
    try {
      const options = await call("challenge", {digest});
      const assertion = await authenticate(options);
      const receipt = await call("approve", {digest, assertion, nonce: options.nonce});
      if (receipt.status !== "reserved" || receipt.request_id !== id) throw new Error();
      status.textContent = "Approval recorded. Deployment is reserved for the worker.";
    } catch {
      status.textContent = "Approval could not be confirmed. Reload to review the request.";
    }
  };
}

if (/^[0-9a-f]{32}$/.test(id || "")) {
  review().catch(() => { status.textContent = "This deployment request is unavailable."; });
}
