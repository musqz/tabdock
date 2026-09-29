# Protocol

```
extension <-- native messaging (stdio, 4-byte native-endian length + JSON) --> relay
relay     <-- Unix socket $XDG_RUNTIME_DIR/tabdock.sock (JSON lines) --> panel
```

The relay (`lib/native-host/tabdock-nmhost`) forwards messages unchanged in both
directions, with two additions: it sends `resync` to the extension whenever the panel
(re)connects, and it adds `browserPid` (its parent process = the browser) to `hello`.
`TABDOCK_SOCKET` overrides the socket path (tests).

## Extension -> panel

| type    | fields | notes |
|---------|--------|-------|
| `hello` | `browser`, `version`, `features`, `browserPid` (added by relay) | sent on every resync, before `state`. `browser` is what `getBrowserInfo()` reports, which is unreliable (Zen says "Firefox"), so the panel names the browser from `/proc/<browserPid>/exe` and only falls back to this. `features` lists what the extension handles beyond what every version did (`close_tab`, `pin_tab`, `containers`, `reopen_in_container`, `restore_tab`, `bookmarks`, `history`): the panel offers only those, so an older extension (no `features`) never gets a `✕` or a menu item that does nothing |
| `state` | `focusedWindowId`, `containerOrder[]`, `containers[]`, `groups[]`, `workspaces[]`, `windows[]` | full snapshot, debounced 50 ms after any change |

`containers[]`: `{cookieStoreId, name, color, colorCode, icon}`.
`windows[]`: `{id, focused, workspaceId, tabs[]}`; `tabs[]`: `{id, index, title, url, favIconUrl, cookieStoreId, active, pinned, audible, discarded, hidden, groupId, workspaceId}`.
`groups[]`: Firefox's own tab groups, `{id, title, color, collapsed}` (`tabGroups.query`); a tab's `groupId` is
one of them, or `null`. Only shown: the panel changes no group.
`focusedWindowId` is the last browser window that had focus (it keeps its value while another app is active).
Tabs without a container have `cookieStoreId: "firefox-default"`.
`containerOrder` is the user's own order of the container sections: cookieStoreIds, kept by the extension
(per browser profile, in `storage.local`), because Firefox cannot reorder containers itself. Ids named there
come first in that order (unknown ones are ignored); containers not named keep the browser's order after them.

`workspaces[]`: `{id, name, icon, color, cookieStoreId}` in the order they were made (per browser profile, in
`storage.local`); `icon` (an emoji or a few characters), `color` (one of the container colours: `blue`,
`turquoise`, `green`, `yellow`, `orange`, `red`, `pink`, `purple`, `toolbar`) and `cookieStoreId` (the container
its new tabs open in) are `null` when unset, and an extension older than them sends only `id` and `name` (the
panel then offers no way to set them). A window's
`workspaceId` is the workspace it shows; a tab's is the workspace it belongs to (both kept in the browser
session, `sessions.setWindowValue` / `setTabValue`, so they survive a restart although ids change). The
extension hides (`tabs.hide`) every tab of another workspace than its window's, and shows its own; pinned
tabs cannot be hidden, so they show in every workspace. The window always shows the workspace of its active
tab. Until a second workspace is created (or the first renamed) the list is `[{id: "default", name:
"Default"}]`, every id is `"default"`, nothing is stored and no tab is ever hidden or shown. The panel
offers no workspaces in Zen (it has its own) or from an older extension (no `workspaces` key).

## Panel -> extension

| type           | fields | notes |
|----------------|--------|-------|
| `resync`       | (none) | sent by the relay on panel connect; extension replies `hello` + `state` and starts pushing snapshots |
| `panel_disconnected` | (none) | sent by the relay when the panel goes away; extension stops pushing snapshots until the next `resync` |
| `activate_tab` | `tabId`, `windowId` | activates the tab and focuses its window |
| `close_tab` | `tabId` | closes the tab (`tabs.remove`). With workspaces in use, when it is the only tab its window shows (every other one hidden), the window's workspace gets a new tab first, so Firefox does not close the window and the other workspaces' tabs with it (`browser.tabs.closeWindowWithLastTab`) |
| `get_bookmarks` | (none) | the extension answers with `bookmarks`: `{granted: false}` while the optional `bookmarks` permission is not granted, else `{granted: true, tree}`, nodes `{title, children}` (folder) or `{title, url}` (`http(s)` only). It sends the same unasked when the permission is granted |
| `search_history` | `query` | the extension answers with `history`: `{granted: false}` while the optional `history` permission is not granted, else `{granted: true, query, items}`, at most 200 `{title, url, lastVisitTime}` (`http(s)` only, newest first) for pages matching `query` (all when empty). It sends `history` with an empty `query` unasked when the permission is granted |
| `open_url` | `url` (`http(s)`), `windowId` | opens the page in a new tab of that window and focuses it |
| `open_options` | (none) | opens the extension's options page (where the permission is granted) |
| `restore_tab` | (none) | reopens the tab (or window) closed last, as Ctrl+Shift+T does (`sessions.restore()`): in its container, and back in its workspace, which the window then shows because the restored tab is the active one. Only an extension that lists `restore_tab` in its `features` gets it |
| `create_container` | `name`, and optionally `color`, `icon` | a new container; without a colour, the first container colour no container has yet, and the `circle` icon |
| `update_container` | `cookieStoreId`, and any of `name`, `color`, `icon` | changes what it names; an empty name, or a colour or icon Firefox does not offer, is ignored |
| `remove_container` | `cookieStoreId` | as Firefox's own settings do: its tabs close first (each as `close_tab` closes one, so never a window with other workspaces' hidden tabs), then the container goes and Firefox deletes its cookies. A workspace that opened its new tabs in it opens them in none from then on |
| `reopen_in_container` | `tabId`, `cookieStoreId` | a tab cannot change its container, so its page opens anew in that one (`firefox-default`: none), right after it, pinned if it was and in the same workspace, and the original closes: the page reloads and its back/forward history stays behind. Pages an extension may not open (`about:config`, `file:`, ...) stay where they are |
| `pin_tab` | `tabId`, `pinned` | pins (`true`) or unpins the tab; a pinned tab shows in every workspace, an unpinned one joins the workspace its window shows |
| `move_tab` | `tabId`, `index` | `tabs.move`: `index` is the tab's final position in its window (it leaves its old place first, so moving forward lands one earlier than the target's index); the resulting `tabs.onMoved` triggers a new `state` |
| `set_container_order` | `order[]` (cookieStoreIds) | stores the order of the panel's container sections and pushes a new `state`; the panel also shows it at once without waiting |
| `new_tab` | `cookieStoreId`, `windowId` | `tabs.create` in that container and window (the `+` on a container section), even "No container" in a workspace with a container of its own; the resulting `tabs.onCreated` triggers a new `state` |
| `switch_workspace` | `windowId`, `workspaceId` | the window shows that workspace: its tab used last becomes active (a new tab if it has none), the others' tabs are hidden |
| `new_workspace` | `windowId`, `name` | adds a workspace (an empty name becomes "Workspace N") and switches the window to it, on a new tab |
| `rename_workspace` | `workspaceId`, `name` | names are trimmed and cut at 64 characters; an empty one is ignored |
| `remove_workspace` | `workspaceId` | closes nothing: its tabs, and the windows that showed it, go to its neighbour (the one before it, or after it if it was first). The last workspace stays |
| `edit_workspace` | `workspaceId`, and any of `icon`, `color`, `cookieStoreId` | sets what it names; an empty, `null` or unknown value (a colour containers do not have, a container that does not exist) clears it. Icons are trimmed and cut at 8 characters |
| `move_tab_to_workspace` | `tabId`, `workspaceId` | the tab joins that workspace; if it was the active tab of a window showing another one, the window stays and activates its own tab used last (a new tab if none) |

A tab that is created (new tab, link, another window) joins the workspace its window shows, unless the session
already knows its workspace (restored, or reopened after closing it: it goes back there). If that workspace has a
container, a tab created on the new-tab page (`about:newtab`, `about:home`) in no container, and not asked for by
the panel, is reopened in that container at the same place and the original closed, as is the new tab an empty
workspace gets. A removed container is cleared from every workspace. The extension's keyboard shortcuts
(`commands`: `next-workspace`, `previous-workspace`, `workspace-1` … `workspace-9`) switch the focused window
like `switch_workspace`, with no message from the panel. A tab dragged to another
window joins that window's workspace, and an unpinned tab the workspace it was unpinned in. A new window shows
the workspace of the window focused before it.

(`focus_window`, once planned, is not needed: `activate_tab` focuses the tab's window.)

## Command line -> panel

The panel takes one message from a client that is no relay: `tabdock --find` connects to the same socket, sends it
and disconnects. The panel answers nothing, and the client never sends `hello`, so it is never listed as a browser.
With no panel listening, `--find` prints `tabdock: not running` and exits 1.

| type   | fields | notes |
|--------|--------|-------|
| `find` | (none) | shows the panel (even while hidden) with its find window, where the arrow keys highlight a tab; sent again while that window is up, it closes it |
