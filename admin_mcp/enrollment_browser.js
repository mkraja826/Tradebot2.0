// Helper for an independently authenticated provisioning interface.
// No public enrollment endpoint is provided by this module.
const HOST = "tradingbot.micirql.com";
function decode(value) {
    if (typeof value !== "string" || !/^[A-Za-z0-9_-]+$/.test(value)) throw new Error("Invalid encoding");
    return Uint8Array.from(atob(value.replace(/-/g, "+").replace(/_/g, "/")), c => c.charCodeAt(0));
}
function encode(value) {
    return btoa(String.fromCharCode(...new Uint8Array(value))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
export async function createOperatorPasskey(options) {
    if (!window.isSecureContext || location.origin !== "https://" + HOST || !window.PublicKeyCredential)
        throw new Error("Secure enrollment origin required");
    const challenge = decode(options.challenge);
    const userId = decode(options.user.id);
    if (challenge.length !== 32 || !userId.length || userId.length > 64 || options.rp.id !== HOST)
        throw new Error("Invalid registration options");
    const credential = await navigator.credentials.create({publicKey: {
        challenge,
        rp: {id: HOST, name: "Recover Trading"},
        user: {id: userId, name: options.user.name, displayName: options.user.displayName},
        pubKeyCredParams: [{type: "public-key", alg: -7}, {type: "public-key", alg: -257}],
        authenticatorSelection: {residentKey: "preferred", userVerification: "required"},
        attestation: "none",
        timeout: 120000
    }});
    if (!credential || credential.type !== "public-key") throw new Error("Registration cancelled");
    return JSON.stringify({
        id: credential.id,
        rawId: encode(credential.rawId),
        type: credential.type,
        response: {
            clientDataJSON: encode(credential.response.clientDataJSON),
            attestationObject: encode(credential.response.attestationObject)
        },
        clientExtensionResults: credential.getClientExtensionResults()
    });
}
