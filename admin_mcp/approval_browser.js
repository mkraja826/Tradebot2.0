// Development helper only. No live endpoint or execution capability.
export async function authenticate(options) {
  if (!window.isSecureContext || !navigator.credentials || !window.PublicKeyCredential) {
    throw new Error("Secure passkey authentication unavailable");
  }
  const decode = s => {
    if (typeof s !== "string" || !/^[A-Za-z0-9_-]+$/.test(s)) throw new Error("Invalid encoding");
    return Uint8Array.from(atob(s.replace(/-/g,"+").replace(/_/g,"/")), c => c.charCodeAt(0));
  };
  const encode = b => btoa(String.fromCharCode(...new Uint8Array(b))).replace(/\+/g,"-").replace(/\//g,"_").replace(/=+$/,"");
  const challenge = decode(options.challenge);
  if (challenge.length !== 32) throw new Error("Invalid challenge");
  const credential = await navigator.credentials.get({publicKey:{
    challenge, rpId: options.rpId, timeout: 60000,
    userVerification:"required",
    allowCredentials: options.allowCredentials.map(c=>({type:"public-key",id:decode(c.id)}))
  }});
  if (!credential) throw new Error("Authentication cancelled");
  const r=credential.response;
  return JSON.stringify({id:credential.id,rawId:encode(credential.rawId),type:credential.type,response:{
    clientDataJSON:encode(r.clientDataJSON),authenticatorData:encode(r.authenticatorData),
    signature:encode(r.signature),userHandle:r.userHandle?encode(r.userHandle):null
  },clientExtensionResults:credential.getClientExtensionResults()});
}
