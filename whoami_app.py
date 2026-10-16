"""Tiny demo app behind an ALB authenticate-oidc rule: shows who is logged in.
It has no login code of its own. It reads the X-Amzn-Oidc-Data JWT that the ALB
adds, verifies its ES256 signature with the ALB public key for the region, and
renders the claims (they come from authentik's userinfo endpoint)."""
import base64, functools, html, json, os, time, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
import jwt

REGION = os.environ.get("REGION", "us-east-1")
# Optional but recommended: ARN of the ALB that must have signed the token,
# authentik issuer and OIDC client ID it must have been issued for
EXPECTED_SIGNER = os.environ.get("EXPECTED_SIGNER", "")
EXPECTED_ISSUER = os.environ.get("EXPECTED_ISSUER", "")
EXPECTED_CLIENT = os.environ.get("EXPECTED_CLIENT", "")


@functools.lru_cache(maxsize=32)
def alb_public_key(kid: str) -> str:
    url = f"https://public-keys.auth.elb.{REGION}.amazonaws.com/{kid}"
    with urllib.request.urlopen(url, timeout=5) as resp:
        return resp.read().decode()


def _b64(segment: str) -> bytes:
    segment = segment.rstrip("=")
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


def _b64json(segment: str) -> dict:
    return json.loads(_b64(segment))


def verify(token: str) -> tuple[dict, dict]:
    # The ALB encodes each segment as base64url WITH "=" padding and signs the
    # header and payload exactly as sent, padding included. Generic JWT libraries
    # reject the padding, and stripping it changes the signed bytes, so verify the
    # ES256 signature here over the segments as received.
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("malformed token")
    header = _b64json(parts[0])
    if header.get("alg") != "ES256":
        raise ValueError(f"unexpected alg {header.get('alg')}")
    if EXPECTED_SIGNER and header.get("signer") != EXPECTED_SIGNER:
        raise ValueError(f"unexpected signer {header.get('signer')}")
    if EXPECTED_ISSUER and header.get("iss") != EXPECTED_ISSUER:
        raise ValueError(f"unexpected issuer {header.get('iss')}")
    if EXPECTED_CLIENT and header.get("client") != EXPECTED_CLIENT:
        raise ValueError(f"unexpected client {header.get('client')}")
    key = serialization.load_pem_public_key(alb_public_key(header["kid"]).encode())
    sig = _b64(parts[2])
    if len(sig) != 64:
        raise ValueError("unexpected signature length")
    der = encode_dss_signature(int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:], "big"))
    try:
        key.verify(der, f"{parts[0]}.{parts[1]}".encode(), ec.ECDSA(hashes.SHA256()))
    except InvalidSignature:
        raise ValueError("Signature verification failed") from None
    claims = _b64json(parts[1])
    exp = header.get("exp", claims.get("exp"))
    if not isinstance(exp, (int, float)) or exp < time.time():
        raise ValueError("token expired")
    return header, claims


_jwks_client = None


def verify_access_token(token: str) -> dict:
    """The access token is authentik's own JWT (RS256 when the provider has a signing
    key). Verify it against authentik's JWKS for this application."""
    global _jwks_client
    if not EXPECTED_ISSUER:
        raise ValueError("EXPECTED_ISSUER no está configurado: no se puede buscar el JWKS")
    if _jwks_client is None:
        _jwks_client = jwt.PyJWKClient(EXPECTED_ISSUER + "jwks/", cache_keys=True)
    key = _jwks_client.get_signing_key_from_jwt(token)
    return jwt.decode(
        token, key.key, algorithms=["RS256", "ES256"], issuer=EXPECTED_ISSUER,
        audience=EXPECTED_CLIENT or None, options={"verify_aud": bool(EXPECTED_CLIENT)},
    )


PAGE = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>whoami</title>
<style>
body{{font-family:system-ui,sans-serif;margin:0;background:#0f1115;color:#e8e8e8}}
main{{max-width:1040px;margin:40px auto;padding:0 16px}}
.card{{background:#1a1d24;border-radius:12px;padding:24px;margin-bottom:20px}}
h1{{font-size:28px;margin:0 0 4px}} .muted{{color:#9aa0a6}}
.ok{{color:#4ade80}} .bad{{color:#f87171}}
.chips span{{display:inline-block;background:#2a2f3a;border-radius:999px;padding:4px 10px;margin:4px 6px 0 0;font-size:14px}}
table{{width:100%;border-collapse:collapse;font-size:13px}} td{{padding:6px 8px;border-top:1px solid #2a2f3a;vertical-align:top;word-break:break-all}}
td:first-child{{color:#9aa0a6;white-space:nowrap;width:1%}}
h2{{font-size:20px;margin:0 0 6px}} code{{font-size:13px}}
.tok{{font-family:ui-monospace,Menlo,monospace;font-size:13px;line-height:1.5;word-break:break-all;background:#0f1115;border-radius:8px;padding:12px;margin:12px 0}}
.th{{color:#f07a50}} .tp{{color:#c4a7ff}} .ts{{color:#5ec2e8}}
.cols{{display:grid;grid-template-columns:1fr 1fr;gap:16px}} @media (max-width:760px){{.cols{{grid-template-columns:1fr}}}}
pre{{font-family:ui-monospace,Menlo,monospace;font-size:13px;line-height:1.45;background:#0f1115;border-radius:8px;padding:12px;margin:6px 0 0;white-space:pre-wrap;word-break:break-all}}
.lbl{{font-size:13px;margin:12px 0 0}}
</style></head><body><main>{body}</main></body></html>"""


def render_user(claims: dict, header: dict) -> str:
    e = html.escape
    name = claims.get("name") or claims.get("preferred_username") or claims.get("sub")
    groups = claims.get("groups") or []
    chips = "".join(f"<span>{e(str(g))}</span>" for g in groups) or '<span class="muted">sin grupos</span>'
    exp = claims.get("exp")
    exp_txt = f"{int(exp - time.time())} s" if isinstance(exp, (int, float)) else "?"
    return f"""<div class="card"><p class="muted">Hola,</p><h1>{e(str(name))}</h1>
<p>{e(str(claims.get('email', '')))} · <span class="muted">@{e(str(claims.get('preferred_username', '')))}</span></p>
<div class="chips">{chips}</div>
<p class="ok">✔ Firma del ALB verificada (ES256, kid {e(str(header.get('kid', '')))[:8]}…) · expira en {e(exp_txt)}</p></div>"""


def _decode_segments(token: str) -> tuple[dict, dict]:
    parts = token.split(".")
    return _b64json(parts[0]), _b64json(parts[1])


def _when(ts) -> str:
    if not isinstance(ts, (int, float)):
        return ""
    delta = int(ts - time.time())
    stamp = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(ts))
    return f"{stamp} ({'en ' + str(delta) if delta >= 0 else 'hace ' + str(-delta)} s)"


def render_token(title: str, intro: str, token: str, status: str) -> str:
    e = html.escape
    parts = token.split(".")
    if len(parts) != 3:
        return f'<div class="card"><h2>{e(title)}</h2><p class="bad">No es un JWT</p></div>'
    colored = (f'<span class="th">{e(parts[0])}</span>.<span class="tp">{e(parts[1])}</span>'
               f'.<span class="ts">{e(parts[2])}</span>')
    try:
        head, payload = _decode_segments(token)
    except Exception as exc:  # noqa: BLE001
        return f'<div class="card"><h2>{e(title)}</h2><p class="bad">No se pudo decodificar: {e(str(exc))}</p></div>'
    times = "".join(
        f"<tr><td>{k}</td><td>{e(_when(payload[k]))}</td></tr>"
        for k in ("iat", "auth_time", "exp") if k in payload
    )
    times = f'<table class="lbl">{times}</table>' if times else ""
    return f"""<div class="card"><h2>{e(title)}</h2><p class="muted">{intro}</p>{status}
<div class="tok">{colored}</div>
<div class="cols"><div><p class="lbl th">Header</p><pre>{e(json.dumps(head, indent=2, ensure_ascii=False))}</pre></div>
<div><p class="lbl tp">Payload</p><pre>{e(json.dumps(payload, indent=2, ensure_ascii=False))}</pre>{times}</div></div></div>"""


def render_tokens(headers, alb_ok: str) -> str:
    out = []
    data = headers.get("x-amzn-oidc-data")
    if data:
        out.append(render_token(
            "X-Amzn-Oidc-Data",
            "Lo arma y lo firma el ALB (ES256) con los claims que le devolvió el userinfo de authentik.",
            data, alb_ok))
    access = headers.get("x-amzn-oidc-accesstoken")
    if access:
        try:
            verify_access_token(access)
            st = '<p class="ok">✔ Firma de authentik verificada con su JWKS · issuer y audience correctos</p>'
        except Exception as exc:  # noqa: BLE001
            st = f'<p class="bad">✖ No verificado: {html.escape(str(exc))}</p>'
        out.append(render_token(
            "X-Amzn-Oidc-Accesstoken",
            "El access token que emitió authentik, tal cual. El ALB lo reenvía sin firmarlo.",
            access, st))
    return "".join(out)


def render_headers(headers) -> str:
    e = html.escape
    rows = []
    for k, v in headers.items():
        if k.lower().startswith("x-amzn-oidc") and len(v) > 40:
            v = v[:24] + "…" + v[-8:]  # don't project live tokens on a screen
        rows.append(f"<tr><td>{e(k)}</td><td>{e(v)}</td></tr>")
    return f'<div class="card"><p class="muted">Headers que recibió la app (los tokens, completos, están arriba)</p><table>{"".join(rows)}</table></div>'


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: str, ctype: str = "text/html; charset=utf-8") -> None:
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send(200, "ok", "text/plain")
            return
        if self.path == "/claims.json":
            token = self.headers.get("x-amzn-oidc-data")
            try:
                _, claims = verify(token) if token else ({}, {})
                self._send(200, json.dumps(claims, ensure_ascii=False), "application/json")
            except Exception as exc:  # noqa: BLE001
                self._send(401, json.dumps({"error": str(exc)}), "application/json")
            return
        token = self.headers.get("x-amzn-oidc-data")
        if not token:
            body = '<div class="card"><h1 class="bad">Sin usuario</h1><p>No llegó <code>X-Amzn-Oidc-Data</code>: el request no pasó por la regla authenticate-oidc del ALB.</p></div>'
            self._send(200, PAGE.format(body=body + render_headers(self.headers)))
            return
        try:
            header, claims = verify(token)
            body = render_user(claims, header)
            alb_ok = '<p class="ok">✔ Firma del ALB verificada · signer, issuer, client y exp correctos</p>'
            code = 200
        except Exception as exc:  # noqa: BLE001
            body = f'<div class="card"><h1 class="bad">Token inválido</h1><p>{html.escape(str(exc))}</p></div>'
            alb_ok = f'<p class="bad">✖ {html.escape(str(exc))}</p>'
            code = 401
        self._send(code, PAGE.format(body=body + render_tokens(self.headers, alb_ok) + render_headers(self.headers)))

    def log_message(self, fmt, *args) -> None:
        print(f"{self.address_string()} {fmt % args}", flush=True)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "80"))), Handler).serve_forever()
