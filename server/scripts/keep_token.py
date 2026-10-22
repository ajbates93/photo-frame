"""Create the Google Keep master token for the frame account.

One-off setup, run on the machine that hosts the server:

    uv run python scripts/keep_token.py

How to get the oauth_token value (from the gkeepapi docs): in a browser, sign in to
https://accounts.google.com/EmbeddedSetup with the frame account and accept the
prompts. The page may then show a loading screen. Open the browser developer tools,
go to Application (or Storage) > Cookies, and copy the value of the cookie named
`oauth_token` (it starts with `oauth2_4/`). That value is single-use.

Both the email and the cookie are read without echo. The resulting master token is
written to <data_dir>/keep-token with mode 0600 and is never printed.

data_dir comes from server/config.toml (the same setting the server uses). If that file
is missing, server/secrets is used. If it exists but does not load as a full config (for
example shared_secret is still CHANGE_ME), only its data_dir key is read; if the file is
not valid TOML the script exits with a message. Pass --data-dir to override all of this.
The absolute directory the token was saved to is printed (never the token).
"""
from __future__ import annotations

import argparse
import getpass
import os
import secrets
import sys
import tomllib
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent


def save_token(path: Path, token: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(token)
    os.chmod(path, 0o600)


def default_data_dir() -> Path:
    config = SERVER_DIR / "config.toml"
    if not config.exists():
        return SERVER_DIR / "secrets"
    try:
        with config.open("rb") as f:
            raw = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise SystemExit(
            f"Failed: cannot read {config.name} ({type(e).__name__}); fix it or pass --data-dir"
        ) from e
    value = raw.get("data_dir")
    if value is None:
        return SERVER_DIR / "secrets"
    if not isinstance(value, str) or not value:
        raise SystemExit("Failed: data_dir in config.toml must be a non-empty string")
    return (SERVER_DIR / value).resolve()  # same resolution as load_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Exchange a Google oauth_token cookie for a Keep master token "
        "and save it to <data_dir>/keep-token (mode 0600).",
        epilog=(__doc__ or "").split("\n\n", 1)[-1],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--data-dir", type=Path, default=None,
        help="directory for keep-token (default: data_dir from server/config.toml, "
        "else server/secrets)",
    )
    args = parser.parse_args(argv)

    import gpsoauth

    data_dir = args.data_dir or default_data_dir()

    email = getpass.getpass("Frame account email: ").strip()
    oauth_token = getpass.getpass("oauth_token cookie value: ").strip()
    if not email or not oauth_token:
        print("Failed: email and oauth_token are both required")
        return 1
    android_id = secrets.token_hex(8)  # 16 hex chars
    try:
        result = gpsoauth.exchange_token(email, oauth_token, android_id)
    except Exception as e:  # noqa: BLE001
        print(f"Failed: {type(e).__name__}")
        return 1
    token = result.get("Token") if isinstance(result, dict) else None
    if not token:
        reason = result.get("Error") if isinstance(result, dict) else None
        print(f"Failed: {reason or 'no token returned'}")
        return 1
    save_token(data_dir / "keep-token", token)
    print(f"Saved to {data_dir.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
