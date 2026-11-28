import {authenticate} from "./approval_browser.js";

export async function mountApproval(root, requestId) {
  if (!/^[0-9a-f]{32}$/.test(requestId)) throw new Error("Invalid request ID");
  const call=async (action, body={})=>{
    const response=await fetch("/fixture/"+requestId+"/"+action,{
      method:"POST",credentials:"same-origin",redirect:"error",cache:"no-store",
      headers:{"Content-Type":"application/json"},body:JSON.stringify(body)
    });
    if (!response.ok) throw new Error("Request rejected");
    return response.json();
  };
  const record=await call("request");
  if(record.id!==requestId || record.action!=="test_only" || record.target!=="fixture") throw new Error("Unexpected request");
  const details=document.createElement("pre");
  details.textContent=JSON.stringify(record,null,2);
  const status=document.createElement("p");
  status.setAttribute("role","status");
  status.textContent="Test only — no execution";
  const button=document.createElement("button");
  button.textContent="Verify with passkey";
  root.replaceChildren(details,status,button);
  button.addEventListener("click",async ()=>{
    button.disabled=true;
    try {
      const options=await call("challenge");
      const assertion=await authenticate(options);
      const result=await call("approve",{nonce:options.nonce,assertion});
      if(result.status!=="fixture_verified" || result.execution_effect!=="none") throw new Error("Unexpected result");
      status.textContent="Passkey verified — no operation executed";
    } catch {
      status.textContent="Verification failed or cancelled";
      button.disabled=false;
    }
  });
}
