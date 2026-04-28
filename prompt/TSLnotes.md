The TLS check is conclusive: your connection to OpenAI is being intercepted by Zscaler, and the presented certificate is issued by a Montefiore CA. Windows already trusts that CA, but Python’s default HTTP verification path was using the certifi bundle instead of the Windows trust store. That is why verified TLS failed while OPENAI_DISABLE_SSL_VERIFY=true made it appear to work.

I changed the app to use the system CA store for OpenAI calls and turned SSL verification back on. The relevant changes are in config.py, llm_review.py, llm_connection_test.py, and requirements.txt. I also updated .env to set OPENAI_DISABLE_SSL_VERIFY=false and OPENAI_USE_SYSTEM_CA_STORE=true.


# solution routes:

Yes. In your specific environment, the recurring pattern is:

- Windows trusts your organization’s corporate CA.
- Python libraries often do not use the Windows trust store by default.
- Instead, they use `certifi`, which is a separate bundled CA list.
- Your corporate TLS proxy inserts a certificate chain signed by the Montefiore CA.
- `certifi` does not know that Montefiore CA, so verification fails.

So the short operational answer is: if this happens again on this network, the first thing to suspect is not “OpenAI SSL is broken,” but “Python is validating against the wrong trust store for this environment.”

**Root Cause**

HTTPS verification works by checking whether the server certificate chains back to a trusted root CA.

In your case, the certificate presented for `api.openai.com` is not the public OpenAI certificate chain directly. Zscaler is intercepting the connection and re-signing it with a Montefiore-trusted CA. Windows accepts that because the Montefiore CA is installed in the Windows certificate store. Python’s default `certifi` bundle does not.

So the mismatch is:

- Windows trust: includes your corporate CA
- Python `certifi` trust: does not include your corporate CA

That is why verification failed only in Python’s default path.

**Why `truststore` works**

`truststore` makes Python SSL use the operating system’s trust store instead of the bundled `certifi` CA file.

On your machine, that means:

- Python asks Windows which root CAs are trusted
- Windows includes the Montefiore CA
- The Zscaler-issued certificate chains to that CA
- Verification succeeds

That is why the fix works without turning verification off.

**General Resolution Order**

When you hit this kind of SSL error in the future, the right sequence is:

1. Confirm whether traffic is being intercepted by a corporate proxy or TLS inspection tool.
2. Check whether the OS already trusts the issuing corporate CA.
3. If the OS trusts it but Python fails, switch Python to the OS trust store.
4. Only if that is not possible, point Python at a custom PEM bundle containing the corporate CA.
5. Avoid disabling SSL verification except as a very short-lived diagnostic step.

So yes, in many enterprise Windows environments, `truststore` is the easiest and cleanest Python-side fix.

**When `truststore` is the right answer**

`truststore` is a good solution when all of these are true:

- You are on Windows, macOS, or another OS with the needed CA already installed
- The SSL problem is only happening in Python clients
- You want Python to behave like the rest of the machine

That matches your case.

**When `truststore` is not enough**

`truststore` will not fix everything. It will not help if:

- The corporate CA is not actually installed in the OS trust store
- The proxy is presenting a broken or incomplete chain
- The hostname is wrong
- The cert is expired
- You are running in a container, Linux VM, CI runner, or server that does not have the corporate CA installed

In those cases, you usually need one of these:

- install the corporate CA into that environment’s trust store
- provide a PEM file and configure a CA bundle explicitly
- fix the proxy or certificate deployment itself

**Why not just disable verification?**

Because disabling verification changes the question from:

“Do I trust who I am talking to?”

to:

“Encrypt this connection, but don’t prove who is on the other end.”

That makes interception invisible and removes the main security guarantee of TLS. It is useful for diagnosis, but it is not a sound steady-state fix.

**Practical rule of thumb**

Use this mental model:

- Browser works, Windows tools work, Python fails:
  Python trust-store mismatch is likely.
- Everything fails:
  CA may be missing from the machine entirely, or the proxy/cert chain is broken.
- Only one app fails:
  that app may be hardcoded to `certifi` or a custom CA path.

**In your app**

The relevant logic is now in config.py, llm_review.py, and llm_connection_test.py. The app now prefers the Windows/system CA store for OpenAI TLS, which is why it aligns with how your machine already trusts Montefiore’s CA.

A good general policy for this project is:

- keep `OPENAI_DISABLE_SSL_VERIFY=false`
- keep `OPENAI_USE_SYSTEM_CA_STORE=true` on your Windows corporate machine
- use `OPENAI_CA_BUNDLE` only when running somewhere that does not have the corporate CA installed in the OS

If you want, I can also give you a compact “enterprise Python SSL troubleshooting checklist” you can reuse the next time this happens.

