# HPC log

Every command run against SeaWulf, with what happened. Newest last.

| When (UTC) | Command | Result |
|---|---|---|
| 2026-11-02 | `ssh -o BatchMode=yes -o ConnectTimeout=15 seawulf hostname` (Git Bash, Windows) | `Could not resolve hostname seawulf`: no `seawulf` entry in the Windows `~/.ssh/config`. WSL (which may hold it) failed with `Wsl/Service/0x80072747`. Blocked until the user's connection is set up |
