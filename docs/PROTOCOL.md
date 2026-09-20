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
| `state` | `focusedWindowId`, `containerOrder[]`, `containers[]`, `windows[]` | full snapshot, debounced 50 ms after any change |

`containers[]`: `{cookieStoreId, name, color, colorCode, icon}`.
`windows[]`: `{id, focused, tabs[]}`; `tabs[]`: `{id, index, title, url, favIconUrl, cookieStoreId, active, pinned, audible, discarded}`.
`focusedWindowId` is the last browser window that had focus (it keeps its value while another app is active).
Tabs without a container have `cookieStoreId: "firefox-default"`.
`containerOrder` is the user's own order of the container sections: cookieStoreIds, kept by the extension
(per browser profile, in `storage.local`), because Firefox cannot reorder containers itself. Ids named there
come first in that order (unknown ones are ignored); containers not named keep the browser's order after them.

## Panel -> extension

| type           | fields | notes |
|----------------|--------|-------|
| `resync`       | (none) | sent by the relay on panel connect; extension replies `hello` + `state` and starts pushing snapshots |
| `panel_disconnected` | (none) | sent by the relay when the panel goes away; extension stops pushing snapshots until the next `resync` |
| `activate_tab` | `tabId`, `windowId` | activates the tab and focuses its window |
| `move_tab` | `tabId`, `index` | `tabs.move`: `index` is the tab's final position in its window (it leaves its old place first, so moving forward lands one earlier than the target's index); the resulting `tabs.onMoved` triggers a new `state` |
| `set_container_order` | `order[]` (cookieStoreIds) | stores the order of the panel's container sections and pushes a new `state`; the panel also shows it at once without waiting |

Later milestones add `close_tab`, `new_tab`, `pin_tab` and `container_*`.
