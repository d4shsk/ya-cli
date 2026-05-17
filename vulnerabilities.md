# vulnerabilities.md

## Current Security Notes

- The CLI can modify files in the selected workspace. Path traversal is blocked by resolving paths and checking that they remain inside the workspace, but symlink-heavy projects should still be treated carefully.
- Shell execution is disabled by default. If enabled with `--allow-shell`, commands run with the user's local permissions and can still be dangerous even after confirmation.
- Tool arguments come from an LLM. The code validates tool names and workspace paths, but every new tool should be treated as untrusted input until validated.
- The fallback parser accepts legacy text tool calls such as `[TOOL_CALL_START]write {...}`. This is intentionally limited to known tool names, but malformed model output may still fail and should be logged rather than executed blindly.
- API credentials are read from environment variables or `.env`. Avoid committing `.env` files or pasting tokens into prompts.
- `.env` is intentionally ignored by `.gitignore`, but local malware, shell history, screenshots, or accidental copy-paste can still expose IAM tokens. Rotate the token if it is shared or leaked.
- Do not bypass TLS verification to work around certificate errors. Install/update the Python certificate bundle instead, otherwise API credentials could be exposed to a machine-in-the-middle attack.
- Prompt history is saved as plain text in `~/.yandexgpt/history` by default. Do not paste secrets into prompts; delete or relocate the history file with `YANDEXGPT_HISTORY` if needed.
