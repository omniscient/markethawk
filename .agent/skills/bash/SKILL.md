---
name: Bash Skill (PowerShell 5.1)
description: A collection of PowerShell 5.1 commands and patterns that mirror common Bash operations for file-system navigation, searching, and script execution on Windows.
---

# Bash Skill (PowerShell 5.1)

This skill provides a standardized set of commands and patterns for interacting with the Windows terminal (PowerShell 5.1) using common Linux-style aliases and logic.

## Multi-Line Commands

In PowerShell, the continuation character is the **backtick** (`` ` ``), whereas in Bash it is the backslash (`\`).

```powershell
# Example of a multi-line command in PowerShell 5.1
git commit -m "feat: implement bash skill" `
  --author="Antigravity <ai@gemini.com>" `
  --date="2026-04-03T14:15:00"
```

## Multi-Operation Commands (Chaining)

PowerShell 5.1 does **not** support `&&` or `||`. You must use the semicolon (`;`) for sequential execution or an `if` block to simulate conditional execution.

### Sequential Execution (Standard `;`)
```powershell
# Runs command2 regardless of command1's success
command1; command2
```

### Conditional Execution (Simulating `&&`)
```powershell
# Runs command2 only if command1 succeeds
command1; if ($?) { command2 }
```

## Common Aliases (Linux-style)

PowerShell 5.1 includes built-in aliases for many common Bash commands. Use these to maintain a "bash-like" feel while staying compatible with the host OS.

| Bash Alias | PS Cmdlet | Notes |
|------------|-----------|-------|
| `ls` | `Get-ChildItem` | Lists directory contents |
| `cat` | `Get-Content` | Reads file content |
| `rm` | `Remove-Item` | Deletes files/directories (use `-Recurse -Force` for `rm -rf`) |
| `cp` | `Copy-Item` | Copies files/directories |
| `mv` | `Move-Item` | Moves/renames files/directories |
| `pwd` | `Get-Location` | Prints current working directory |
| `clear` | `Clear-Host` | Clears the terminal screen |
| `grep` | `Select-String` | Use `grep "pattern" file` style, or `cat file | Select-String "pattern"` |

## Advanced Operations

### Searching for Text (`grep` equivalent)
```powershell
# Case-insensitive search for "error" in all .py files
ls -Recurse *.py | Select-String "error"
```

### JSON Processing
Instead of `jq`, PowerShell 5.1 has native JSON support.
```powershell
# Parse a JSON file and extract a property
cat settings.json | ConvertFrom-Json | Select-Object -ExpandProperty version
```

### Environment Variables
```powershell
# Read an environment variable
$env:PATH

# Set an environment variable (for the current session)
$env:DEBUG = "true"
```

### Network Requests (`curl` alternative)
```powershell
# Basic GET request
Invoke-RestMethod -Uri "http://localhost:8000/api/health"
```

---

> [!TIP]
> When using `run_command`, always ensure that backticks (`` ` ``) are used for line continuation and that multiple operations are separated by `; if ($?) { ... }` if strict sequencing is required.
