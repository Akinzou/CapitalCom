<!-- Included by index.md and getting-started.md. README.md keeps its own copy, because PyPI
renders the README as it is and cannot include another file. -->

```bash
pip install capitalcom
```

Python 3.11 or newer; on an older Python, pip installs 1.0.4, which this site does not describe.

Optional extras:

- `pip install "capitalcom[streaming]"` for live quotes and bars over the WebSocket;
- `pip install "capitalcom[encryption]"` to send the password encrypted at login.
