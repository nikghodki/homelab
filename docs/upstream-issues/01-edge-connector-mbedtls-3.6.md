# Edge Connector 1.0.9 doesn't build against mbedTLS 3.6: `mbedtls_ssl_conf_min_version` is deprecated and `-Werror` is on

Target: github.com/cisco-ai-defense/defenseclaw

## Upstream check (2026-11-15)

- Issues and PRs searched: `mbedtls`, `mbedtls_ssl_conf_min_version`, `deprecated-declarations`. Nothing reports it.
- Open PR #1343 (edge connector hardening) edits `tls_engine.c` and says its end-to-end test used mbedTLS 3.6, but it
  doesn't change the call. `main` still has it at `edge-connector/src/comms/tls_engine.c:174`.
- No release after 1.0.9 yet. Status: **not reported, not fixed.**

## Version

DefenseClaw 1.0.9 (release source tarball), Edge Connector production build.

## Environment

- Raspberry Pi 4, Debian 13 (trixie) arm64
- gcc 14.2.0 (Debian 14.2.0-19)
- `libmbedtls-dev` 3.6.6-0.1~deb13u1 (`MBEDTLS_VERSION_NUMBER` 3.6.6)

## Steps to reproduce

```bash
cd defenseclaw-1.0.9
cmake -S edge-connector -B edge-connector/build-prod -DCMAKE_BUILD_TYPE=Release \
  -DDCLAW_PROFILE=STANDARD -DDCLAW_DEV_MODE=OFF -DDCLAW_ALLOW_HMAC_OTA=ON
cmake --build edge-connector/build-prod -j4
```

## Expected

The production build compiles against the distro's mbedTLS 3.x, which `INSTALL.md` asks for.

## Actual

```text
src/comms/tls_engine.c:174:5: error: 'mbedtls_ssl_conf_min_version' is deprecated [-Werror=deprecated-declarations]
cc1: all warnings being treated as errors
```

## Evidence

- `edge-connector/CMakeLists.txt:91` adds `-Wall -Wextra -Werror` to every target.
- `edge-connector/src/comms/tls_engine.c:174-176`:
  `mbedtls_ssl_conf_min_version(&tls_conf, MBEDTLS_SSL_MAJOR_VERSION_3, MBEDTLS_SSL_MINOR_VERSION_3);`
- mbedTLS 3.6 declares it `MBEDTLS_DEPRECATED` (`/usr/include/mbedtls/ssl.h:4496`). It has been deprecated since 3.2
  in favour of `mbedtls_ssl_conf_min_tls_version()`.
- We compiled every `src/**/*.c` with the build's own include paths and flags. This is the only deprecated mbedTLS
  symbol the engine uses. The other calls (`mbedtls_pk_parse_key`, `mbedtls_md_hmac_*`, `mbedtls_x509_crt_parse`,
  `mbedtls_ssl_get_version`, ...) are clean on 3.6.

## Suggested fix

```c
#if MBEDTLS_VERSION_NUMBER >= 0x03020000
    mbedtls_ssl_conf_min_tls_version(&tls_conf, MBEDTLS_SSL_VERSION_TLS1_2);
#else
    mbedtls_ssl_conf_min_version(&tls_conf, MBEDTLS_SSL_MAJOR_VERSION_3, MBEDTLS_SSL_MINOR_VERSION_3);
#endif
```

Also add a CI job that builds the production profile against a current distro mbedTLS (for example Debian 13), so a
new deprecation shows up before a release.

## Workaround we used

Turn off only this warning-as-error and keep `-Werror` for everything else:

```bash
cmake ... -DCMAKE_C_FLAGS=-Wno-error=deprecated-declarations
```

The build, `ctest` and the daemon then work. The TLS minimum is still TLS 1.2.
