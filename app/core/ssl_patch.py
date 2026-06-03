import ssl

def apply_ssl_patch():
    """
    Robustly patches Python's ssl module to bypass certificate verification
    in local development without crashing when libraries (like aiosmtplib /
    fastapi-mail) call ssl.create_default_context(purpose=ssl.Purpose.CLIENT_AUTH).

    The original ssl._create_unverified_context does NOT accept a 'purpose'
    argument (it's an SSLContext factory, not create_default_context), so we
    must absorb all arguments and build the context ourselves.
    """
    try:
        # 1. Patch default HTTPS context creator
        ssl._create_default_https_context = ssl._create_unverified_context

        # 2. Replace create_default_context with a no-verify wrapper.
        #    We swallow ALL args/kwargs (including 'purpose', 'cafile', etc.)
        #    and just return an unverified SSLContext.
        def _unverified_context_wrapper(*args, **kwargs):
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            return ctx

        ssl.create_default_context = _unverified_context_wrapper

    except Exception as exc:
        print(f"[SSL Patch Warning] Could not apply SSL patch: {exc}")
