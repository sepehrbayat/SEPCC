from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _script_text(name: str) -> str:
    return (_repo_root() / "scripts" / name).read_text(encoding="utf-8")


def _braced_body(text: str, declaration: str) -> str:
    start = text.index(declaration)
    brace_start = text.index("{", start)
    depth = 0

    for index, char in enumerate(text[brace_start:], start=brace_start):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[brace_start + 1 : index]

    raise AssertionError(f"Unclosed function body for {declaration}")


def test_install_sh_installs_or_updates_claude_code() -> None:
    text = _script_text("install.sh")
    body = _braced_body(text, "install_or_update_claude()")
    main = text[text.index('parse_args "$@"') :]

    assert "Installs or updates Claude Code" in text
    assert "if command -v claude >/dev/null 2>&1; then" in body
    assert "claude_path=$(command -v claude)" in body
    assert "npm prefix -g" in body
    assert "run env CLAUDE_CODE_PACKAGE_MANAGER_AUTO_UPDATE=1" in body
    assert "require_command npm" in body
    assert "run npm install -g @anthropic-ai/claude-code@latest" in body
    assert body.index("command -v claude") < body.index(
        "claude_path=$(command -v claude)"
    )
    assert 'step "Installing or updating Claude Code"\ninstall_or_update_claude' in main
    assert "npm install -g @anthropic-ai/claude-code@latest" not in main


def test_install_sh_installs_missing_uv_without_self_update() -> None:
    body = _braced_body(_script_text("install.sh"), "install_or_update_uv()")

    assert "if command -v uv >/dev/null 2>&1; then" in body
    assert body.count("run uv self update") == 1

    update_index = body.index("run uv self update")
    return_index = body.index("return 0", update_index)
    installer_index = body.index("run_uv_installer")
    verification_index = body.index('if [ "$dry_run" -eq 0 ] && ! command -v uv')

    assert update_index < return_index < installer_index < verification_index


def test_install_ps1_installs_or_updates_claude_code() -> None:
    text = _script_text("install.ps1")
    body = _braced_body(text, "function Install-OrUpdateClaude")

    assert "Installs or updates Claude Code" in text
    assert "$claudeCommand = Get-Command claude -ErrorAction SilentlyContinue" in body
    assert "Test-NpmClaudePath $claudeCommand.Source" in body
    assert '$env:CLAUDE_CODE_PACKAGE_MANAGER_AUTO_UPDATE = "1"' in body
    assert 'Assert-CommandAvailable "npm"' in body
    assert (
        'Invoke-InstallCommand -FilePath "npm" '
        '-Arguments @("install", "-g", "@anthropic-ai/claude-code@latest")'
    ) in body
    assert (
        'Write-Step "Installing or updating Claude Code"\nInstall-OrUpdateClaude'
        in text
    )


def test_install_ps1_installs_missing_uv_without_self_update() -> None:
    body = _braced_body(_script_text("install.ps1"), "function Install-OrUpdateUv")
    self_update = 'Invoke-InstallCommand -FilePath "uv" -Arguments @("self", "update")'

    assert "if (Get-Command uv -ErrorAction SilentlyContinue)" in body
    assert body.count(self_update) == 1

    update_index = body.index(self_update)
    return_index = body.index("return", update_index)
    installer_index = body.index("Invoke-UvInstaller")
    verification_index = body.index("if ((-not $DryRun)")

    assert update_index < return_index < installer_index < verification_index
