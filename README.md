# claude-code-plugins

My Claude Code mods, in one private marketplace.

| Plugin | What it does | Based on |
|---|---|---|
| [ribbon](plugins/ribbon) | Usage band above the prompt: 7D and 5H usage left with reset times, and a coffee cup that steams while the prompt cache is warm. | [robonuggets/ribbon](https://github.com/robonuggets/ribbon) (MIT) |
| [savvy-progress](plugins/savvy-progress) | Task progress band above the prompt and a live Agents panel (`/agents-info`). | [JohnnyVizz/claude-kit](https://github.com/JohnnyVizz/claude-kit) savvy-progress 1.2.1 (MIT) |

The two stack together: savvy-progress on top, ribbon's usage row underneath.

Tools (not plugins, set up on their own):

| Tool | What it does |
|---|---|
| [claude-pinger](tools/claude-pinger) | Windows scheduled task that sends `hello` on Haiku when no 5-hour window is open, so resets land earlier in the day; also reports usage per window. |

## Install

In a terminal (this repository is private, so GitHub must be signed in on the machine, for example with `gh auth login`):

```
claude plugin marketplace add mpeyal/claude-code-plugins
claude plugin install ribbon@mpeyal-plugins --scope user
claude plugin install savvy-progress@mpeyal-plugins --scope user
```

Then run `/reload-plugins` in Claude Code, or start a new session.

Optional savvy-progress settings (open its Agents panel for any subagent, and follow Claude Code's language):

```
echo {"autoOpen":"any","language":"auto"} | claude plugin configure savvy-progress@mpeyal-plugins --values-stdin
```

On Windows with the Claude desktop app, the `claude` on PATH may be older than the app's own. If a command fails, run the app's copy instead:
`& "$env:LOCALAPPDATA\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\claude-code\<version>\<id>\claude.exe" plugin ...`

## Changes from the originals

**ribbon**
- Light and dark palettes; `/ribbon-theme light|dark` switches them (no argument toggles) and the choice is remembered.
- A coffee cup (steaming when warm, frosted when cold) replaces the robot.
- Padding inside the band, and other mods' bands are drawn above it, so usage always sits at the bottom.
- Desktop layout measures about 8 px per column, so the band stacks instead of clipping when the window is narrow.

**savvy-progress**
- The desktop band row leaves 150 px for the crew count and dismiss button (was 96, which clipped the dismiss).
- Any helpers (subagents) started from the main session raise the band by themselves as "Helpers at work", one task per helper, reading Done when all finish. A plan reported through its `progress` tool still takes over the band.

## Updating

Edit the plugin folders, commit and push, then on each machine:

```
claude plugin marketplace update mpeyal-plugins
```

and `/reload-plugins`.
