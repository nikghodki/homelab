# tools

Approved MCP servers, one folder each (plan P4.3):

```
tools/<server>/
  server.yaml    # URL / transport, owner host, which agents may use it
  tools.json     # output of the server's tools/list, as approved
  tools.sha256   # hash of the approved descriptions; a nightly job compares the live server against it
```

CI runs the Cisco AI Defense mcp-scanner (static, YARA) on every `tools.json` and fails on HIGH findings.
