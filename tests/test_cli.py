import subprocess
import sys


def test_create_admin_cli_does_not_accept_password_argument() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.cli",
            "create-admin",
            "--username",
            "admin",
            "--password",
            "must-not-be-accepted",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "unrecognized arguments: --password" in result.stderr
