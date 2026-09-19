# Protocol

```
extension <-- native messaging (stdio, 4-byte native-endian length + JSON) --> relay
relay     <-- Unix socket $XDG_RUNTIME_DIR/openbox-sidepanel.sock (JSON lines) --> panel
```

The relay (`lib/native-host/sidepanel-nmhost`) forwards messages unchanged in both
directions, with two additions: it sends `resync` to the extension whenever the panel
(re)connects, and it adds `browserPid` (its parent process = the browser) to `hello`.
`SIDEPANEL_SOCKET` overrides the socket path (tests).

## Extension -> panel

| type    | fields | notes |
|---------|--------|-------|
| `hello` | `browser`, `version`, `browserPid` (added by relay) | sent on every resync, before `state`. `browser` is what `getBrowserInfo()` reports, which is unreliable (Zen says "Firefox"), so the panel names the browser from `/proc/<browserPid>/exe` and only falls back to this |
| `state` | `focusedWindowId`, `containers[]`, `windows[]` | full snapshot, debounced 50 ms after any change |

`containers[]`: `{cookieStoreId, name, color, colorCode, icon}`.
`windows[]`: `{id, focused, tabs[]}`; `tabs[]`: `{id, index, title, url, favIconUrl, cookieStoreId, active, pinned, audible, discarded}`.
`focusedWindowId` is the last browser window that had focus (it keeps its value while another app is active).
Tabs without a container have `cookieStoreId: "firefox-default"`.

## Panel -> extension

| type           | fields | notes |
|----------------|--------|-------|
| `resync`       | (none) | sent by the relay on panel connect; extension replies `hello` + `state` and starts pushing snapshots |
| `panel_disconnected` | (none) | sent by the relay when the panel goes away; extension stops pushing snapshots until the next `resync` |
| `activate_tab` | `tabId`, `windowId` | activates the tab and focuses its window |

Later milestones add `close_tab`, `new_tab`, `move_tab`, `pin_tab` and `container_*`.
