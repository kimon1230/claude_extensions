"""Tests for hooks/sensitive-file-guard.py PreToolUse hook."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hooks import sensitive_file_guard_mod
from hooks.sensitive_file_guard_mod import _is_sensitive


def _make_payload(tool_name: str, tool_input: dict) -> dict:
    """Build a PreToolUse hook payload."""
    return {"tool_name": tool_name, "tool_input": tool_input}


def _run_main(payload: dict, monkeypatch) -> str:
    """Run main() with *payload* on stdin and return captured stdout."""
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    cap = io.StringIO()
    monkeypatch.setattr("sys.stdout", cap)
    sensitive_file_guard_mod.main()
    return cap.getvalue()


# ---------------------------------------------------------------------------
# Unit tests for _is_sensitive
# ---------------------------------------------------------------------------


class TestIsSensitiveEnvFiles:
    """Env file pattern matching."""

    @pytest.mark.parametrize(
        "path",
        [
            ".env",
            "/home/user/project/.env",
            ".env.local",
            ".env.production",
            ".env.staging",
            ".env.test",
            ".env.development",
        ],
    )
    def test_blocked_env_files(self, path: str) -> None:
        assert _is_sensitive(path) is True

    @pytest.mark.parametrize(
        "path",
        [
            ".env.example",
            ".env.sample",
            ".env.schema",
            ".envrc",
            "/project/.env.example",
        ],
    )
    def test_allowed_env_files(self, path: str) -> None:
        assert _is_sensitive(path) is False


class TestIsSensitiveSSHKeys:
    """SSH and TLS key file patterns."""

    @pytest.mark.parametrize(
        "path",
        [
            "id_rsa",
            "id_rsa.pub",
            "/home/user/.ssh/id_rsa",
            "id_ed25519",
            "id_ed25519.pub",
            "/home/user/.ssh/id_ed25519",
        ],
    )
    def test_ssh_keys_blocked(self, path: str) -> None:
        assert _is_sensitive(path) is True

    @pytest.mark.parametrize(
        "path",
        [
            "server.pem",
            "/etc/ssl/cert.pem",
            "keystore.p12",
            "cert.pfx",
        ],
    )
    def test_tls_certs_blocked(self, path: str) -> None:
        assert _is_sensitive(path) is True


class TestIsSensitiveKeyFiles:
    """*.key files — only blocked when basename contains qualifying keyword."""

    @pytest.mark.parametrize(
        "path",
        [
            "private.key",
            "server.key",
            "tls-cert.key",
            "ssl_private.key",
            "/etc/ssl/private.key",
        ],
    )
    def test_sensitive_key_files_blocked(self, path: str) -> None:
        assert _is_sensitive(path) is True

    @pytest.mark.parametrize(
        "path",
        [
            "translation.key",
            "api.key",
            "cache.key",
            "/project/locales/translation.key",
        ],
    )
    def test_non_sensitive_key_files_allowed(self, path: str) -> None:
        assert _is_sensitive(path) is False


class TestIsSensitiveCredentialFiles:
    """Credential and secret file patterns."""

    @pytest.mark.parametrize(
        "path",
        [
            "credentials",
            "credentials.json",
            "credentials.yaml",
            "secrets",
            "secrets.env",
            "secrets.toml",
            "/home/user/.config/credentials.json",
        ],
    )
    def test_credential_files_blocked(self, path: str) -> None:
        assert _is_sensitive(path) is True

    @pytest.mark.parametrize(
        "path",
        [
            "credentials_validator.py",
            "secrets_manager.py",
            "my_credentials_test.json",
            "user_secrets_util.rb",
        ],
    )
    def test_credential_substrings_allowed(self, path: str) -> None:
        assert _is_sensitive(path) is False


class TestIsSensitivePackageTokens:
    """Package manager token files."""

    @pytest.mark.parametrize("path", [".npmrc", ".pypirc", "/home/user/.npmrc"])
    def test_token_files_blocked(self, path: str) -> None:
        assert _is_sensitive(path) is True


class TestIsSensitiveAWSPaths:
    """AWS config path segment matching."""

    @pytest.mark.parametrize(
        "path",
        [
            "/home/user/.aws/credentials",
            "/home/user/.aws/config",
            "~/.aws/credentials",
        ],
    )
    def test_aws_paths_blocked(self, path: str) -> None:
        assert _is_sensitive(path) is True

    def test_aws_unrelated_allowed(self) -> None:
        assert _is_sensitive("/home/user/.aws/cli/cache/abc.json") is False


class TestIsSensitiveNonSensitive:
    """Files that should never be blocked."""

    @pytest.mark.parametrize(
        "path",
        [
            "README.md",
            "main.py",
            "package.json",
            "src/app.ts",
            "/home/user/project/config.yaml",
            "Dockerfile",
        ],
    )
    def test_normal_files_allowed(self, path: str) -> None:
        assert _is_sensitive(path) is False


# ---------------------------------------------------------------------------
# Integration tests: Read tool
# ---------------------------------------------------------------------------


class TestReadToolBlocking:
    """Read tool payloads that should be blocked."""

    def test_read_env_blocked(self, monkeypatch) -> None:
        payload = _make_payload("Read", {"file_path": "/project/.env"})
        out = _run_main(payload, monkeypatch)
        result = json.loads(out)
        assert result["decision"] == "block"
        assert ".env" in result["reason"]

    def test_read_ssh_key_blocked(self, monkeypatch) -> None:
        payload = _make_payload("Read", {"file_path": "/home/user/.ssh/id_rsa"})
        out = _run_main(payload, monkeypatch)
        result = json.loads(out)
        assert result["decision"] == "block"
        assert "id_rsa" in result["reason"]

    def test_read_credentials_json_blocked(self, monkeypatch) -> None:
        payload = _make_payload("Read", {"file_path": "/app/credentials.json"})
        out = _run_main(payload, monkeypatch)
        result = json.loads(out)
        assert result["decision"] == "block"

    def test_read_aws_credentials_blocked(self, monkeypatch) -> None:
        payload = _make_payload("Read", {"file_path": "/home/user/.aws/credentials"})
        out = _run_main(payload, monkeypatch)
        result = json.loads(out)
        assert result["decision"] == "block"


class TestReadToolAllowed:
    """Read tool payloads that should pass through (empty stdout)."""

    def test_read_normal_file_allowed(self, monkeypatch) -> None:
        payload = _make_payload("Read", {"file_path": "/project/README.md"})
        out = _run_main(payload, monkeypatch)
        assert out == ""

    def test_read_env_example_allowed(self, monkeypatch) -> None:
        payload = _make_payload("Read", {"file_path": "/project/.env.example"})
        out = _run_main(payload, monkeypatch)
        assert out == ""

    def test_read_empty_path_allowed(self, monkeypatch) -> None:
        payload = _make_payload("Read", {"file_path": ""})
        out = _run_main(payload, monkeypatch)
        assert out == ""

    def test_read_missing_file_path_allowed(self, monkeypatch) -> None:
        payload = _make_payload("Read", {})
        out = _run_main(payload, monkeypatch)
        assert out == ""

    def test_read_non_string_path_allowed(self, monkeypatch) -> None:
        payload = _make_payload("Read", {"file_path": 42})
        out = _run_main(payload, monkeypatch)
        assert out == ""


# ---------------------------------------------------------------------------
# Integration tests: Bash tool
# ---------------------------------------------------------------------------


class TestBashToolBlocking:
    """Bash tool payloads that should be blocked."""

    def test_cat_env_blocked(self, monkeypatch) -> None:
        payload = _make_payload("Bash", {"command": "cat .env"})
        out = _run_main(payload, monkeypatch)
        result = json.loads(out)
        assert result["decision"] == "block"

    def test_grep_env_blocked(self, monkeypatch) -> None:
        payload = _make_payload("Bash", {"command": "grep KEY .env.production"})
        out = _run_main(payload, monkeypatch)
        result = json.loads(out)
        assert result["decision"] == "block"

    def test_cat_ssh_key_blocked(self, monkeypatch) -> None:
        payload = _make_payload("Bash", {"command": "cat /home/user/.ssh/id_rsa"})
        out = _run_main(payload, monkeypatch)
        result = json.loads(out)
        assert result["decision"] == "block"

    def test_cat_credentials_blocked(self, monkeypatch) -> None:
        payload = _make_payload("Bash", {"command": "cat credentials.json"})
        out = _run_main(payload, monkeypatch)
        result = json.loads(out)
        assert result["decision"] == "block"

    def test_head_pem_blocked(self, monkeypatch) -> None:
        payload = _make_payload("Bash", {"command": "head -n 5 server.pem"})
        out = _run_main(payload, monkeypatch)
        result = json.loads(out)
        assert result["decision"] == "block"


class TestBashToolAllowed:
    """Bash tool payloads that should pass through."""

    def test_cat_readme_allowed(self, monkeypatch) -> None:
        payload = _make_payload("Bash", {"command": "cat README.md"})
        out = _run_main(payload, monkeypatch)
        assert out == ""

    def test_echo_env_allowed(self, monkeypatch) -> None:
        """Command containing 'env' as a word (not a file) should not be blocked."""
        payload = _make_payload("Bash", {"command": "echo $ENV_VAR"})
        out = _run_main(payload, monkeypatch)
        assert out == ""

    def test_empty_command_allowed(self, monkeypatch) -> None:
        payload = _make_payload("Bash", {"command": ""})
        out = _run_main(payload, monkeypatch)
        assert out == ""

    def test_missing_command_allowed(self, monkeypatch) -> None:
        payload = _make_payload("Bash", {})
        out = _run_main(payload, monkeypatch)
        assert out == ""

    def test_non_string_command_allowed(self, monkeypatch) -> None:
        payload = _make_payload("Bash", {"command": 123})
        out = _run_main(payload, monkeypatch)
        assert out == ""

    def test_malformed_shell_string_allowed(self, monkeypatch) -> None:
        """Unparseable shell string should not crash — just allow through."""
        payload = _make_payload("Bash", {"command": "echo 'unterminated"})
        out = _run_main(payload, monkeypatch)
        assert out == ""


# ---------------------------------------------------------------------------
# Integration tests: other tools and edge cases
# ---------------------------------------------------------------------------


class TestOtherToolsIgnored:
    """Non-Read, non-Bash tools should always pass through."""

    def test_edit_tool_ignored(self, monkeypatch) -> None:
        payload = _make_payload("Edit", {"file_path": "/project/.env"})
        out = _run_main(payload, monkeypatch)
        assert out == ""

    def test_grep_tool_ignored(self, monkeypatch) -> None:
        payload = _make_payload("Grep", {"pattern": "SECRET", "path": ".env"})
        out = _run_main(payload, monkeypatch)
        assert out == ""

    def test_unknown_tool_ignored(self, monkeypatch) -> None:
        payload = _make_payload("CustomTool", {"file_path": ".env"})
        out = _run_main(payload, monkeypatch)
        assert out == ""


class TestMainEdgeCases:
    """Edge cases in main() parsing."""

    def test_empty_stdin(self, monkeypatch) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO(""))
        cap = io.StringIO()
        monkeypatch.setattr("sys.stdout", cap)
        sensitive_file_guard_mod.main()
        assert cap.getvalue() == ""

    def test_malformed_json(self, monkeypatch) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO("{invalid json!!"))
        cap = io.StringIO()
        monkeypatch.setattr("sys.stdout", cap)
        sensitive_file_guard_mod.main()
        assert cap.getvalue() == ""

    def test_non_dict_payload(self, monkeypatch) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps([1, 2, 3])))
        cap = io.StringIO()
        monkeypatch.setattr("sys.stdout", cap)
        sensitive_file_guard_mod.main()
        assert cap.getvalue() == ""

    def test_non_dict_tool_input(self, monkeypatch) -> None:
        payload = {"tool_name": "Read", "tool_input": "not a dict"}
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
        cap = io.StringIO()
        monkeypatch.setattr("sys.stdout", cap)
        sensitive_file_guard_mod.main()
        assert cap.getvalue() == ""

    def test_exception_logged_to_stderr(self, monkeypatch) -> None:
        """Any exception in main() is caught and logged to stderr, not raised."""

        def _boom(_size):
            raise RuntimeError("boom")

        monkeypatch.setattr("sys.stdin", type("FakeStdin", (), {"read": _boom})())
        cap_err = io.StringIO()
        monkeypatch.setattr("sys.stderr", cap_err)
        cap_out = io.StringIO()
        monkeypatch.setattr("sys.stdout", cap_out)
        sensitive_file_guard_mod.main()
        assert "sensitive-file-guard:" in cap_err.getvalue()
        assert cap_out.getvalue() == ""
