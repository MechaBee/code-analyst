from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol
from urllib.parse import quote
from uuid import uuid4

from fastapi import HTTPException, Request, Response

from code_analyst_contracts import PendingRegistrationInvite, User

from .app_state_store import AppStateStore
from .config import Settings


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_email(email: str) -> str:
    normalized = email.strip().lower()
    if not normalized:
        raise ValueError("Email is required.")
    return normalized


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class AuthError(RuntimeError):
    pass


class AuthForbiddenError(AuthError):
    pass


class AuthConflictError(AuthError):
    pass


class AuthNotFoundError(AuthError):
    pass


class AuthTokenExpiredError(AuthError):
    pass


class AuthTokenUsedError(AuthError):
    pass


@dataclass(slots=True)
class AuthAccount:
    account_id: str
    tenant_id: str
    email: str
    created_at: datetime
    last_login_at: datetime | None = None


@dataclass(slots=True)
class RegistrationInviteRecord:
    invite_id: str
    tenant_id: str
    email: str
    name_hint: str | None
    team_ids: list[str]
    is_admin: bool
    token_hash: str
    created_by: str | None
    created_at: datetime
    expires_at: datetime
    used_at: datetime | None = None


@dataclass(slots=True)
class SignInLinkRecord:
    link_id: str
    tenant_id: str
    email: str
    token_hash: str
    created_at: datetime
    expires_at: datetime
    used_at: datetime | None = None


@dataclass(slots=True)
class SessionRecord:
    session_id: str
    tenant_id: str
    account_id: str
    email: str
    token_hash: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
    last_seen_at: datetime | None = None


class AuthStoreProvider(Protocol):
    kind: str

    def count_accounts(self, *, tenant_id: str) -> int:
        ...

    def list_accounts(self, *, tenant_id: str) -> list[AuthAccount]:
        ...

    def get_account_by_email(self, *, tenant_id: str, email: str) -> AuthAccount | None:
        ...

    def create_account(self, *, tenant_id: str, email: str) -> AuthAccount:
        ...

    def touch_account_login(self, *, account_id: str, timestamp: datetime) -> None:
        ...

    def create_registration_invite(
        self,
        *,
        invite: RegistrationInviteRecord,
    ) -> None:
        ...

    def get_registration_invite_by_token_hash(
        self,
        *,
        token_hash: str,
    ) -> RegistrationInviteRecord | None:
        ...

    def list_pending_registration_invites(
        self,
        *,
        tenant_id: str,
        current_time: datetime,
    ) -> list[RegistrationInviteRecord]:
        ...

    def consume_registration_invite(
        self,
        *,
        token_hash: str,
        used_at: datetime,
    ) -> RegistrationInviteRecord:
        ...

    def create_sign_in_link(
        self,
        *,
        link: SignInLinkRecord,
    ) -> None:
        ...

    def consume_sign_in_link(
        self,
        *,
        token_hash: str,
        used_at: datetime,
    ) -> SignInLinkRecord:
        ...

    def create_session(self, *, session: SessionRecord) -> None:
        ...

    def get_session_by_token_hash(
        self,
        *,
        token_hash: str,
        current_time: datetime,
    ) -> SessionRecord | None:
        ...

    def revoke_session(self, *, session_id: str, revoked_at: datetime) -> None:
        ...

    def touch_session(self, *, session_id: str, last_seen_at: datetime) -> None:
        ...


class AuthStoreService:
    def __init__(
        self,
        *,
        providers: list[AuthStoreProvider],
        default_provider_kind: str,
    ) -> None:
        self._providers = {provider.kind: provider for provider in providers}
        if default_provider_kind not in self._providers:
            raise AuthError(f"Unsupported auth store provider {default_provider_kind!r}.")
        self._provider = self._providers[default_provider_kind]

    def count_accounts(self, *, tenant_id: str) -> int:
        return self._provider.count_accounts(tenant_id=tenant_id)

    def list_accounts(self, *, tenant_id: str) -> list[AuthAccount]:
        return self._provider.list_accounts(tenant_id=tenant_id)

    def get_account_by_email(self, *, tenant_id: str, email: str) -> AuthAccount | None:
        return self._provider.get_account_by_email(tenant_id=tenant_id, email=email)

    def create_account(self, *, tenant_id: str, email: str) -> AuthAccount:
        return self._provider.create_account(tenant_id=tenant_id, email=email)

    def touch_account_login(self, *, account_id: str, timestamp: datetime) -> None:
        self._provider.touch_account_login(account_id=account_id, timestamp=timestamp)

    def create_registration_invite(self, *, invite: RegistrationInviteRecord) -> None:
        self._provider.create_registration_invite(invite=invite)

    def get_registration_invite_by_token_hash(
        self,
        *,
        token_hash: str,
    ) -> RegistrationInviteRecord | None:
        return self._provider.get_registration_invite_by_token_hash(token_hash=token_hash)

    def list_pending_registration_invites(
        self,
        *,
        tenant_id: str,
        current_time: datetime,
    ) -> list[RegistrationInviteRecord]:
        return self._provider.list_pending_registration_invites(
            tenant_id=tenant_id,
            current_time=current_time,
        )

    def consume_registration_invite(
        self,
        *,
        token_hash: str,
        used_at: datetime,
    ) -> RegistrationInviteRecord:
        return self._provider.consume_registration_invite(token_hash=token_hash, used_at=used_at)

    def create_sign_in_link(self, *, link: SignInLinkRecord) -> None:
        self._provider.create_sign_in_link(link=link)

    def consume_sign_in_link(
        self,
        *,
        token_hash: str,
        used_at: datetime,
    ) -> SignInLinkRecord:
        return self._provider.consume_sign_in_link(token_hash=token_hash, used_at=used_at)

    def create_session(self, *, session: SessionRecord) -> None:
        self._provider.create_session(session=session)

    def get_session_by_token_hash(
        self,
        *,
        token_hash: str,
        current_time: datetime,
    ) -> SessionRecord | None:
        return self._provider.get_session_by_token_hash(
            token_hash=token_hash,
            current_time=current_time,
        )

    def revoke_session(self, *, session_id: str, revoked_at: datetime) -> None:
        self._provider.revoke_session(session_id=session_id, revoked_at=revoked_at)

    def touch_session(self, *, session_id: str, last_seen_at: datetime) -> None:
        self._provider.touch_session(session_id=session_id, last_seen_at=last_seen_at)


class SqliteAuthStoreProvider:
    kind = "sqlite"

    def __init__(self, settings: Settings) -> None:
        self._path = Path(settings.auth_sqlite_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._ensure_schema()

    def count_accounts(self, *, tenant_id: str) -> int:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM accounts WHERE tenant_id = ?",
                (tenant_id,),
            ).fetchone()
            return int(row["count"]) if row is not None else 0

    def list_accounts(self, *, tenant_id: str) -> list[AuthAccount]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT account_id, tenant_id, email, created_at, last_login_at
                FROM accounts
                WHERE tenant_id = ?
                ORDER BY email ASC
                """,
                (tenant_id,),
            ).fetchall()
            return [self._account_from_row(row) for row in rows]

    def get_account_by_email(self, *, tenant_id: str, email: str) -> AuthAccount | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT account_id, tenant_id, email, created_at, last_login_at
                FROM accounts
                WHERE tenant_id = ? AND email = ?
                """,
                (tenant_id, email),
            ).fetchone()
            return self._account_from_row(row) if row is not None else None

    def create_account(self, *, tenant_id: str, email: str) -> AuthAccount:
        account = AuthAccount(
            account_id=f"acct_{uuid4().hex[:12]}",
            tenant_id=tenant_id,
            email=email,
            created_at=utc_now(),
        )
        with self._lock, self._connect() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO accounts (account_id, tenant_id, email, created_at, last_login_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        account.account_id,
                        account.tenant_id,
                        account.email,
                        account.created_at.isoformat(),
                        None,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise AuthConflictError("Account already exists for this email.") from error
        return account

    def touch_account_login(self, *, account_id: str, timestamp: datetime) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE accounts SET last_login_at = ? WHERE account_id = ?",
                (timestamp.isoformat(), account_id),
            )

    def create_registration_invite(
        self,
        *,
        invite: RegistrationInviteRecord,
    ) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO registration_invites (
                    invite_id,
                    tenant_id,
                    email,
                    name_hint,
                    team_ids_json,
                    is_admin,
                    token_hash,
                    created_by,
                    created_at,
                    expires_at,
                    used_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    invite.invite_id,
                    invite.tenant_id,
                    invite.email,
                    invite.name_hint,
                    json.dumps(invite.team_ids, sort_keys=True),
                    1 if invite.is_admin else 0,
                    invite.token_hash,
                    invite.created_by,
                    invite.created_at.isoformat(),
                    invite.expires_at.isoformat(),
                    invite.used_at.isoformat() if invite.used_at is not None else None,
                ),
            )

    def get_registration_invite_by_token_hash(
        self,
        *,
        token_hash: str,
    ) -> RegistrationInviteRecord | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT invite_id, tenant_id, email, name_hint, team_ids_json, is_admin,
                       token_hash, created_by, created_at, expires_at, used_at
                FROM registration_invites
                WHERE token_hash = ?
                """,
                (token_hash,),
            ).fetchone()
            return self._invite_from_row(row) if row is not None else None

    def list_pending_registration_invites(
        self,
        *,
        tenant_id: str,
        current_time: datetime,
    ) -> list[RegistrationInviteRecord]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT invite_id, tenant_id, email, name_hint, team_ids_json, is_admin,
                       token_hash, created_by, created_at, expires_at, used_at
                FROM registration_invites
                WHERE tenant_id = ?
                  AND used_at IS NULL
                  AND expires_at > ?
                ORDER BY created_at DESC
                """,
                (tenant_id, current_time.isoformat()),
            ).fetchall()
            return [self._invite_from_row(row) for row in rows]

    def consume_registration_invite(
        self,
        *,
        token_hash: str,
        used_at: datetime,
    ) -> RegistrationInviteRecord:
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT invite_id, tenant_id, email, name_hint, team_ids_json, is_admin,
                       token_hash, created_by, created_at, expires_at, used_at
                FROM registration_invites
                WHERE token_hash = ?
                """,
                (token_hash,),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise AuthNotFoundError("Registration invite not found.")

            invite = self._invite_from_row(row)
            if invite.used_at is not None:
                connection.rollback()
                raise AuthTokenUsedError("Registration invite has already been used.")
            if invite.expires_at <= used_at:
                connection.rollback()
                raise AuthTokenExpiredError("Registration invite has expired.")

            cursor = connection.execute(
                """
                UPDATE registration_invites
                SET used_at = ?
                WHERE invite_id = ? AND used_at IS NULL
                """,
                (used_at.isoformat(), invite.invite_id),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                raise AuthTokenUsedError("Registration invite has already been used.")

            connection.commit()
            return invite

    def create_sign_in_link(self, *, link: SignInLinkRecord) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO sign_in_links (
                    link_id,
                    tenant_id,
                    email,
                    token_hash,
                    created_at,
                    expires_at,
                    used_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    link.link_id,
                    link.tenant_id,
                    link.email,
                    link.token_hash,
                    link.created_at.isoformat(),
                    link.expires_at.isoformat(),
                    link.used_at.isoformat() if link.used_at is not None else None,
                ),
            )

    def consume_sign_in_link(
        self,
        *,
        token_hash: str,
        used_at: datetime,
    ) -> SignInLinkRecord:
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT link_id, tenant_id, email, token_hash, created_at, expires_at, used_at
                FROM sign_in_links
                WHERE token_hash = ?
                """,
                (token_hash,),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise AuthNotFoundError("Sign-in link not found.")

            link = self._sign_in_link_from_row(row)
            if link.used_at is not None:
                connection.rollback()
                raise AuthTokenUsedError("Sign-in link has already been used.")
            if link.expires_at <= used_at:
                connection.rollback()
                raise AuthTokenExpiredError("Sign-in link has expired.")

            cursor = connection.execute(
                """
                UPDATE sign_in_links
                SET used_at = ?
                WHERE link_id = ? AND used_at IS NULL
                """,
                (used_at.isoformat(), link.link_id),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                raise AuthTokenUsedError("Sign-in link has already been used.")

            connection.commit()
            return link

    def create_session(self, *, session: SessionRecord) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO sessions (
                    session_id,
                    tenant_id,
                    account_id,
                    token_hash,
                    created_at,
                    expires_at,
                    revoked_at,
                    last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session.session_id,
                    session.tenant_id,
                    session.account_id,
                    session.token_hash,
                    session.created_at.isoformat(),
                    session.expires_at.isoformat(),
                    session.revoked_at.isoformat() if session.revoked_at is not None else None,
                    session.last_seen_at.isoformat() if session.last_seen_at is not None else None,
                ),
            )

    def get_session_by_token_hash(
        self,
        *,
        token_hash: str,
        current_time: datetime,
    ) -> SessionRecord | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT sessions.session_id,
                       sessions.tenant_id,
                       sessions.account_id,
                       accounts.email,
                       sessions.token_hash,
                       sessions.created_at,
                       sessions.expires_at,
                       sessions.revoked_at,
                       sessions.last_seen_at
                FROM sessions
                JOIN accounts ON accounts.account_id = sessions.account_id
                WHERE sessions.token_hash = ?
                  AND sessions.revoked_at IS NULL
                  AND sessions.expires_at > ?
                """,
                (token_hash, current_time.isoformat()),
            ).fetchone()
            return self._session_from_row(row) if row is not None else None

    def revoke_session(self, *, session_id: str, revoked_at: datetime) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE sessions
                SET revoked_at = COALESCE(revoked_at, ?)
                WHERE session_id = ?
                """,
                (revoked_at.isoformat(), session_id),
            )

    def touch_session(self, *, session_id: str, last_seen_at: datetime) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE sessions SET last_seen_at = ? WHERE session_id = ?",
                (last_seen_at.isoformat(), session_id),
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _ensure_schema(self) -> None:
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS accounts (
                    account_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    email TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_login_at TEXT,
                    UNIQUE (tenant_id, email)
                );

                CREATE TABLE IF NOT EXISTS registration_invites (
                    invite_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    email TEXT NOT NULL,
                    name_hint TEXT,
                    team_ids_json TEXT NOT NULL,
                    is_admin INTEGER NOT NULL,
                    token_hash TEXT NOT NULL UNIQUE,
                    created_by TEXT,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    used_at TEXT
                );

                CREATE TABLE IF NOT EXISTS sign_in_links (
                    link_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    email TEXT NOT NULL,
                    token_hash TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    used_at TEXT
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    account_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
                    token_hash TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    revoked_at TEXT,
                    last_seen_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_accounts_tenant_email
                    ON accounts (tenant_id, email);
                CREATE INDEX IF NOT EXISTS idx_invites_tenant_email
                    ON registration_invites (tenant_id, email);
                CREATE INDEX IF NOT EXISTS idx_sign_in_links_tenant_email
                    ON sign_in_links (tenant_id, email);
                CREATE INDEX IF NOT EXISTS idx_sessions_account
                    ON sessions (account_id);
                """
            )

    def _account_from_row(self, row: sqlite3.Row) -> AuthAccount:
        return AuthAccount(
            account_id=row["account_id"],
            tenant_id=row["tenant_id"],
            email=row["email"],
            created_at=self._parse_datetime(row["created_at"]),
            last_login_at=self._parse_datetime(row["last_login_at"]),
        )

    def _invite_from_row(self, row: sqlite3.Row) -> RegistrationInviteRecord:
        team_ids = json.loads(row["team_ids_json"]) if row["team_ids_json"] else []
        return RegistrationInviteRecord(
            invite_id=row["invite_id"],
            tenant_id=row["tenant_id"],
            email=row["email"],
            name_hint=row["name_hint"],
            team_ids=team_ids if isinstance(team_ids, list) else [],
            is_admin=bool(row["is_admin"]),
            token_hash=row["token_hash"],
            created_by=row["created_by"],
            created_at=self._parse_datetime(row["created_at"]) or utc_now(),
            expires_at=self._parse_datetime(row["expires_at"]) or utc_now(),
            used_at=self._parse_datetime(row["used_at"]),
        )

    def _sign_in_link_from_row(self, row: sqlite3.Row) -> SignInLinkRecord:
        return SignInLinkRecord(
            link_id=row["link_id"],
            tenant_id=row["tenant_id"],
            email=row["email"],
            token_hash=row["token_hash"],
            created_at=self._parse_datetime(row["created_at"]) or utc_now(),
            expires_at=self._parse_datetime(row["expires_at"]) or utc_now(),
            used_at=self._parse_datetime(row["used_at"]),
        )

    def _session_from_row(self, row: sqlite3.Row) -> SessionRecord:
        return SessionRecord(
            session_id=row["session_id"],
            tenant_id=row["tenant_id"],
            account_id=row["account_id"],
            email=row["email"],
            token_hash=row["token_hash"],
            created_at=self._parse_datetime(row["created_at"]) or utc_now(),
            expires_at=self._parse_datetime(row["expires_at"]) or utc_now(),
            revoked_at=self._parse_datetime(row["revoked_at"]),
            last_seen_at=self._parse_datetime(row["last_seen_at"]),
        )

    def _parse_datetime(self, value: str | None) -> datetime | None:
        if value is None:
            return None
        return datetime.fromisoformat(value)


class AuthService:
    def __init__(
        self,
        *,
        settings: Settings,
        store: AuthStoreService,
        app_state_store: AppStateStore,
    ) -> None:
        self._settings = settings
        self._store = store
        self._app_state_store = app_state_store
        self._lock = threading.RLock()

    def create_bootstrap_admin_invitation(
        self,
        *,
        tenant_id: str,
        email: str,
        name: str | None,
        expires_in_hours: int | None,
        bootstrap_secret: str,
    ) -> tuple[str, datetime]:
        if bootstrap_secret != self._settings.auth_bootstrap_secret:
            raise AuthForbiddenError("Bootstrap secret is invalid.")

        if self._store.count_accounts(tenant_id=tenant_id) > 0:
            raise AuthConflictError("Bootstrap is no longer available for this tenant.")

        return self._create_registration_invitation(
            tenant_id=tenant_id,
            email=email,
            name=name,
            team_ids=[],
            is_admin=True,
            created_by=None,
            expires_in_hours=expires_in_hours,
        )

    def create_registration_invitation(
        self,
        *,
        tenant_id: str,
        email: str,
        name: str | None,
        team_ids: list[str],
        is_admin: bool,
        created_by: str,
        expires_in_hours: int | None,
    ) -> tuple[str, datetime]:
        return self._create_registration_invitation(
            tenant_id=tenant_id,
            email=email,
            name=name,
            team_ids=team_ids,
            is_admin=is_admin,
            created_by=created_by,
            expires_in_hours=expires_in_hours,
        )

    def preview_registration_invitation(self, *, token: str) -> RegistrationInviteRecord:
        invite = self._require_registration_invite(token=token)
        self._ensure_record_usable(invite)
        return invite

    def consume_registration_invitation(
        self,
        *,
        token: str,
        name: str | None,
    ) -> tuple[User, str]:
        token_hash_value = hash_token(token)
        normalized_name = name.strip() if name is not None else None
        used_at = utc_now()
        with self._lock:
            preview = self._store.get_registration_invite_by_token_hash(
                token_hash=token_hash_value
            )
            if preview is None:
                raise AuthNotFoundError("Registration invite not found.")
            self._ensure_record_usable(preview)
            if self._store.get_account_by_email(
                tenant_id=preview.tenant_id,
                email=preview.email,
            ) is not None:
                raise AuthConflictError("This email already has a registered account.")

            invite = self._store.consume_registration_invite(
                token_hash=token_hash_value,
                used_at=used_at,
            )
            account = self._store.create_account(
                tenant_id=invite.tenant_id,
                email=invite.email,
            )
            user = self._sync_invited_user(
                invite=invite,
                explicit_name=normalized_name,
            )
            session_token = self._create_session_for_account(
                account=account,
                created_at=used_at,
            )
            self._store.touch_account_login(account_id=account.account_id, timestamp=used_at)
            return user, session_token

    def create_sign_in_link(
        self,
        *,
        tenant_id: str,
        email: str,
        expires_in_hours: int | None,
    ) -> tuple[str, datetime]:
        normalized_email = normalize_email(email)
        account = self._store.get_account_by_email(
            tenant_id=tenant_id,
            email=normalized_email,
        )
        if account is None:
            raise AuthConflictError("Only registered users can receive sign-in links.")
        user = self._app_state_store.get_user(tenant_id, normalized_email)
        if user is None:
            raise AuthConflictError("User registry entry is missing for this account.")

        token = secrets.token_urlsafe(32)
        created_at = utc_now()
        expires_at = created_at + timedelta(
            hours=expires_in_hours
            if expires_in_hours is not None
            else self._settings.auth_sign_in_link_ttl_seconds / 3600
        )
        self._store.create_sign_in_link(
            link=SignInLinkRecord(
                link_id=f"signin_{uuid4().hex[:12]}",
                tenant_id=tenant_id,
                email=normalized_email,
                token_hash=hash_token(token),
                created_at=created_at,
                expires_at=expires_at,
            )
        )
        return self._build_sign_in_url(token), expires_at

    def consume_sign_in_link(self, *, token: str) -> tuple[User, str]:
        token_hash_value = hash_token(token)
        used_at = utc_now()
        with self._lock:
            link = self._store.consume_sign_in_link(
                token_hash=token_hash_value,
                used_at=used_at,
            )
            account = self._store.get_account_by_email(
                tenant_id=link.tenant_id,
                email=link.email,
            )
            if account is None:
                raise AuthConflictError("This sign-in link does not belong to a registered user.")
            user = self._app_state_store.get_user(link.tenant_id, link.email)
            if user is None:
                raise AuthConflictError("User registry entry is missing for this account.")
            session_token = self._create_session_for_account(
                account=account,
                created_at=used_at,
            )
            self._store.touch_account_login(account_id=account.account_id, timestamp=used_at)
            return user, session_token

    def authenticate_session(self, *, token: str) -> User:
        session = self._store.get_session_by_token_hash(
            token_hash=hash_token(token),
            current_time=utc_now(),
        )
        if session is None:
            raise AuthNotFoundError("Session not found.")
        user = self._app_state_store.get_user(session.tenant_id, session.email)
        if user is None:
            raise AuthNotFoundError("User not found for session.")
        self._store.touch_session(session_id=session.session_id, last_seen_at=utc_now())
        return user

    def logout_session(self, *, token: str | None) -> None:
        if not token:
            return
        session = self._store.get_session_by_token_hash(
            token_hash=hash_token(token),
            current_time=utc_now(),
        )
        if session is None:
            return
        self._store.revoke_session(session_id=session.session_id, revoked_at=utc_now())

    def list_pending_registration_invites(self, *, tenant_id: str) -> list[PendingRegistrationInvite]:
        invites = self._store.list_pending_registration_invites(
            tenant_id=tenant_id,
            current_time=utc_now(),
        )
        return [
            PendingRegistrationInvite(
                invite_id=invite.invite_id,
                tenant_id=invite.tenant_id,
                email=invite.email,
                name_hint=invite.name_hint,
                team_ids=invite.team_ids,
                is_admin=invite.is_admin,
                created_by=invite.created_by,
                created_at=invite.created_at,
                expires_at=invite.expires_at,
            )
            for invite in invites
        ]

    def registered_emails(self, *, tenant_id: str) -> set[str]:
        return {account.email for account in self._store.list_accounts(tenant_id=tenant_id)}

    def set_session_cookie(self, response: Response, *, token: str) -> None:
        response.set_cookie(
            key=self._settings.auth_cookie_name,
            value=token,
            httponly=True,
            samesite="lax",
            secure=self._settings.resolved_auth_cookie_secure,
            path="/",
            max_age=self._settings.auth_session_ttl_seconds,
        )

    def clear_session_cookie(self, response: Response) -> None:
        response.delete_cookie(
            key=self._settings.auth_cookie_name,
            httponly=True,
            samesite="lax",
            secure=self._settings.resolved_auth_cookie_secure,
            path="/",
        )

    def _create_registration_invitation(
        self,
        *,
        tenant_id: str,
        email: str,
        name: str | None,
        team_ids: list[str],
        is_admin: bool,
        created_by: str | None,
        expires_in_hours: int | None,
    ) -> tuple[str, datetime]:
        normalized_email = normalize_email(email)
        if self._store.get_account_by_email(tenant_id=tenant_id, email=normalized_email) is not None:
            raise AuthConflictError("This email already has a registered account.")

        token = secrets.token_urlsafe(32)
        created_at = utc_now()
        expires_at = created_at + timedelta(
            hours=expires_in_hours
            if expires_in_hours is not None
            else self._settings.auth_invite_ttl_seconds / 3600
        )
        self._store.create_registration_invite(
            invite=RegistrationInviteRecord(
                invite_id=f"inv_{uuid4().hex[:12]}",
                tenant_id=tenant_id,
                email=normalized_email,
                name_hint=name.strip() if name is not None and name.strip() else None,
                team_ids=team_ids,
                is_admin=is_admin,
                token_hash=hash_token(token),
                created_by=created_by,
                created_at=created_at,
                expires_at=expires_at,
            )
        )
        return self._build_registration_url(token), expires_at

    def _require_registration_invite(self, *, token: str) -> RegistrationInviteRecord:
        invite = self._store.get_registration_invite_by_token_hash(token_hash=hash_token(token))
        if invite is None:
            raise AuthNotFoundError("Registration invite not found.")
        return invite

    def _ensure_record_usable(self, invite: RegistrationInviteRecord) -> None:
        now = utc_now()
        if invite.used_at is not None:
            raise AuthTokenUsedError("Registration invite has already been used.")
        if invite.expires_at <= now:
            raise AuthTokenExpiredError("Registration invite has expired.")

    def _sync_invited_user(
        self,
        *,
        invite: RegistrationInviteRecord,
        explicit_name: str | None,
    ) -> User:
        existing = self._app_state_store.get_user(invite.tenant_id, invite.email)
        preferred_name = (
            explicit_name
            if explicit_name
            else invite.name_hint.strip() if invite.name_hint is not None and invite.name_hint.strip() else None
        )
        if existing is None:
            user = User(
                tenant_id=invite.tenant_id,
                email=invite.email,
                name=preferred_name,
                is_admin=invite.is_admin,
            )
        else:
            user = existing.model_copy(
                update={
                    "name": preferred_name or existing.name,
                    "is_admin": existing.is_admin or invite.is_admin,
                }
            )

        user = self._app_state_store.upsert_user(user)
        for team_id in invite.team_ids:
            try:
                self._app_state_store.add_team_membership(
                    invite.tenant_id,
                    team_id,
                    invite.email,
                )
            except KeyError:
                continue
        return user

    def _create_session_for_account(
        self,
        *,
        account: AuthAccount,
        created_at: datetime,
    ) -> str:
        token = secrets.token_urlsafe(32)
        expires_at = created_at + timedelta(seconds=self._settings.auth_session_ttl_seconds)
        self._store.create_session(
            session=SessionRecord(
                session_id=f"sess_{uuid4().hex[:12]}",
                tenant_id=account.tenant_id,
                account_id=account.account_id,
                email=account.email,
                token_hash=hash_token(token),
                created_at=created_at,
                expires_at=expires_at,
                last_seen_at=created_at,
            )
        )
        return token

    def _build_registration_url(self, token: str) -> str:
        base = self._settings.app_public_url.rstrip("/")
        return f"{base}/auth/register?token={quote(token)}"

    def _build_sign_in_url(self, token: str) -> str:
        base = self._settings.app_public_url.rstrip("/")
        return f"{base}/auth/sign-in?token={quote(token)}"


class RequestAuthBackend(Protocol):
    kind: str

    def authenticate_request(self, *, request: Request, app_state_store: AppStateStore) -> User:
        ...


class HeaderAuthBackend:
    kind = "header"

    def authenticate_request(self, *, request: Request, app_state_store: AppStateStore) -> User:
        tenant_id = request.headers.get("X-Tenant-Id")
        user_email = request.headers.get("X-User-Email")
        if not tenant_id or not user_email:
            raise HTTPException(
                status_code=401,
                detail="Missing X-Tenant-Id or X-User-Email header.",
            )

        normalized_email = normalize_email(user_email)
        db = app_state_store.load_tenant_db(tenant_id)
        has_admin = any(existing.is_admin for existing in db.users.values())
        user = db.users.get(normalized_email)
        if user is None:
            user = User(
                tenant_id=tenant_id,
                email=normalized_email,
                is_admin=not has_admin,
            )
            user = app_state_store.upsert_user(user)
        elif not has_admin and not user.is_admin:
            user = user.model_copy(update={"is_admin": True})
            user = app_state_store.upsert_user(user)
        return user


class SessionCookieAuthBackend:
    kind = "session_cookie"

    def __init__(self, *, settings: Settings, auth_service: AuthService) -> None:
        self._settings = settings
        self._auth_service = auth_service

    def authenticate_request(self, *, request: Request, app_state_store: AppStateStore) -> User:
        del app_state_store
        token = request.cookies.get(self._settings.auth_cookie_name)
        if not token:
            raise HTTPException(status_code=401, detail="Authentication required.")
        try:
            return self._auth_service.authenticate_session(token=token)
        except AuthError as error:
            raise HTTPException(status_code=401, detail=str(error)) from error


def build_auth_store(settings: Settings) -> AuthStoreService:
    provider_kind = settings.auth_store.strip().lower()
    if provider_kind != "sqlite":
        raise AuthError(f"Unsupported auth store provider {settings.auth_store!r}.")
    return AuthStoreService(
        providers=[SqliteAuthStoreProvider(settings)],
        default_provider_kind=provider_kind,
    )


def build_request_auth_backend(
    settings: Settings,
    *,
    auth_service: AuthService,
) -> RequestAuthBackend:
    backend_kind = settings.auth_backend.strip().lower()
    if backend_kind == "header":
        return HeaderAuthBackend()
    if backend_kind == "session_cookie":
        return SessionCookieAuthBackend(settings=settings, auth_service=auth_service)
    raise AuthError(f"Unsupported auth backend {settings.auth_backend!r}.")
