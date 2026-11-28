import {createOperatorPasskey} from "./enrollment_browser.js";
const form = document.getElementById("enrollment");
const status = document.getElementById("status");
const button = document.getElementById("register");
const tokenField = document.getElementById("token");
async function post(action, body, token) {
    const response = await fetch("/admin/enroll/" + action, {
        method: "POST", credentials: "omit", cache: "no-store", redirect: "error",
        headers: {"Content-Type":"application/json", "Authorization":"Bearer " + token},
        body: JSON.stringify(body)
    });
    if (!response.ok) throw new Error("Enrollment request failed");
    return response.json();
}
form.addEventListener("submit", async event => {
    event.preventDefault();
    if (button.disabled) return;
    button.disabled = true;
    const token = tokenField.value;
    tokenField.value = "";
    const operator = document.getElementById("operator").value;
    try {
        status.textContent = "Preparing registration…";
        const options = await post("options", {operator}, token);
        const response = await createOperatorPasskey(options);
        const result = await post("complete", {operator, challenge:options.challenge, response}, token);
        if (result.status !== "registered") throw new Error("Registration not confirmed");
        form.hidden = true;
        status.textContent = "Passkey registered successfully.";
    } catch {
        status.textContent = "Enrollment failed or was cancelled. Verify the session with your administrator before retrying.";
        button.disabled = false;
    }
});
