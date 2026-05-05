from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any

from code_analyst_contracts import (
    Checkout,
    RepositoryDefinition,
    RepositoryDefinitionUpdateTeamsResponse,
    Team,
    TeamMemberAddResponse,
    TeamMemberRemoveResponse,
    TeamMembership,
    User,
    UserMeResponse,
)
from pydantic import BaseModel, Field

from .object_store import ObjectStore, ObjectStoreKeyNotFound


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# In-memory per-tenant DB structure
# ---------------------------------------------------------------------------


class TenantAppStateDB(BaseModel):
    tenant_id: str
    users: dict[str, User] = Field(default_factory=dict)
    teams: dict[str, Team] = Field(default_factory=dict)
    memberships: list[TeamMembership] = Field(default_factory=list)
    repo_definitions: dict[str, RepositoryDefinition] = Field(default_factory=dict)
    checkouts: dict[str, Checkout] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AppStateStore:
    """Lightweight in-memory relational DB per tenant, persisted to S3 as JSON.

    Optimistic locking via S3 ETag. Single instance (local-first) means simple
    threading.Lock per tenant is sufficient.
    """

    def __init__(self, object_store: ObjectStore) -> None:
        self._object_store = object_store
        self._cache: dict[str, TenantAppStateDB] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._master_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Low-level load / save
    # ------------------------------------------------------------------

    def _db_key(self, tenant_id: str) -> str:
        return f"tenants/{tenant_id}/db/app_state.json"

    def _get_lock(self, tenant_id: str) -> threading.Lock:
        with self._master_lock:
            if tenant_id not in self._locks:
                self._locks[tenant_id] = threading.Lock()
            return self._locks[tenant_id]

    def load_tenant_db(self, tenant_id: str) -> TenantAppStateDB:
        """Load tenant DB from in-memory cache or S3."""
        with self._get_lock(tenant_id):
            if tenant_id in self._cache:
                return self._cache[tenant_id]
            try:
                payload = self._object_store.download_json(
                    self._db_key(tenant_id)
                )
                db = TenantAppStateDB.model_validate(payload)
            except ObjectStoreKeyNotFound:
                db = TenantAppStateDB(tenant_id=tenant_id)
            self._cache[tenant_id] = db
            return db

    def save_tenant_db(self, tenant_id: str, db: TenantAppStateDB) -> None:
        """Save tenant DB back to S3 and update cache."""
        with self._get_lock(tenant_id):
            db.metadata["updated_at"] = utc_now().isoformat()
            db.metadata["version"] = db.metadata.get("version", 0) + 1
            self._object_store.upload_json(
                self._db_key(tenant_id),
                db.model_dump(mode="json"),
            )
            self._cache[tenant_id] = db

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------

    def upsert_user(self, user: User) -> User:
        db = self.load_tenant_db(user.tenant_id)
        db.users[user.email] = user
        self.save_tenant_db(user.tenant_id, db)
        return user

    def get_user(self, tenant_id: str, email: str) -> User | None:
        db = self.load_tenant_db(tenant_id)
        return db.users.get(email)

    def list_users(self, tenant_id: str) -> list[User]:
        db = self.load_tenant_db(tenant_id)
        return list(db.users.values())

    def me(self, tenant_id: str, email: str) -> UserMeResponse | None:
        user = self.get_user(tenant_id, email)
        if user is None:
            return None
        return UserMeResponse(
            tenant_id=user.tenant_id,
            email=user.email,
            name=user.name,
            is_admin=user.is_admin,
        )

    # ------------------------------------------------------------------
    # Teams
    # ------------------------------------------------------------------

    def create_team(self, team: Team) -> Team:
        db = self.load_tenant_db(team.tenant_id)
        if team.team_id in db.teams:
            raise ValueError(f"Team {team.team_id} already exists")
        db.teams[team.team_id] = team
        self.save_tenant_db(team.tenant_id, db)
        return team

    def get_team(self, tenant_id: str, team_id: str) -> Team | None:
        db = self.load_tenant_db(tenant_id)
        return db.teams.get(team_id)

    def list_teams(self, tenant_id: str) -> list[Team]:
        db = self.load_tenant_db(tenant_id)
        return list(db.teams.values())

    def list_teams_for_user(self, tenant_id: str, user_email: str) -> list[Team]:
        db = self.load_tenant_db(tenant_id)
        team_ids = {
            m.team_id
            for m in db.memberships
            if m.user_email == user_email
        }
        return [db.teams[tid] for tid in team_ids if tid in db.teams]

    # ------------------------------------------------------------------
    # Memberships
    # ------------------------------------------------------------------

    def add_team_membership(
        self,
        tenant_id: str,
        team_id: str,
        user_email: str,
    ) -> TeamMemberAddResponse:
        db = self.load_tenant_db(tenant_id)
        if team_id not in db.teams:
            raise KeyError(f"Team {team_id} not found")
        if user_email not in db.users:
            raise KeyError(f"User {user_email} not found")
        existing = [m for m in db.memberships if m.team_id == team_id and m.user_email == user_email]
        if existing:
            return TeamMemberAddResponse(
                team_id=team_id,
                user_email=user_email,
                joined_at=existing[0].joined_at,
            )
        membership = TeamMembership(
            tenant_id=tenant_id,
            team_id=team_id,
            user_email=user_email,
        )
        db.memberships.append(membership)
        self.save_tenant_db(tenant_id, db)
        return TeamMemberAddResponse(
            team_id=team_id,
            user_email=user_email,
            joined_at=membership.joined_at,
        )

    def remove_team_membership(
        self,
        tenant_id: str,
        team_id: str,
        user_email: str,
    ) -> TeamMemberRemoveResponse:
        db = self.load_tenant_db(tenant_id)
        before = len(db.memberships)
        db.memberships = [
            m for m in db.memberships
            if not (m.team_id == team_id and m.user_email == user_email)
        ]
        if len(db.memberships) == before:
            raise KeyError(f"Membership not found for {user_email} in team {team_id}")
        self.save_tenant_db(tenant_id, db)
        return TeamMemberRemoveResponse(team_id=team_id, user_email=user_email)

    def list_team_members(self, tenant_id: str, team_id: str) -> list[TeamMembership]:
        db = self.load_tenant_db(tenant_id)
        return [m for m in db.memberships if m.team_id == team_id]

    # ------------------------------------------------------------------
    # Repository Definitions
    # ------------------------------------------------------------------

    def create_repo_definition(
        self,
        repo_def: RepositoryDefinition,
    ) -> RepositoryDefinition:
        db = self.load_tenant_db(repo_def.tenant_id)
        if repo_def.repo_def_id in db.repo_definitions:
            raise ValueError(f"Repository definition {repo_def.repo_def_id} already exists")
        db.repo_definitions[repo_def.repo_def_id] = repo_def
        self.save_tenant_db(repo_def.tenant_id, db)
        return repo_def

    def get_repo_definition(
        self,
        tenant_id: str,
        repo_def_id: str,
    ) -> RepositoryDefinition | None:
        db = self.load_tenant_db(tenant_id)
        return db.repo_definitions.get(repo_def_id)

    def list_repo_definitions(
        self,
        tenant_id: str,
        include_archived: bool = False,
    ) -> list[RepositoryDefinition]:
        db = self.load_tenant_db(tenant_id)
        repo_defs = list(db.repo_definitions.values())
        if include_archived:
            return repo_defs
        return [repo_def for repo_def in repo_defs if repo_def.archived_at is None]

    def list_repo_definitions_for_principal(
        self,
        tenant_id: str,
        user_email: str,
        include_archived: bool = False,
    ) -> list[RepositoryDefinition]:
        db = self.load_tenant_db(tenant_id)
        user_team_ids = {
            m.team_id
            for m in db.memberships
            if m.user_email == user_email
        }
        return [
            rd for rd in db.repo_definitions.values()
            if any(tid in user_team_ids for tid in rd.team_ids)
            and (include_archived or rd.archived_at is None)
        ]

    def replace_repo_definition(
        self,
        tenant_id: str,
        repo_def: RepositoryDefinition,
    ) -> RepositoryDefinition:
        db = self.load_tenant_db(tenant_id)
        if repo_def.repo_def_id not in db.repo_definitions:
            raise KeyError(f"Repository definition {repo_def.repo_def_id} not found")
        db.repo_definitions[repo_def.repo_def_id] = repo_def
        self.save_tenant_db(tenant_id, db)
        return repo_def

    def archive_repo_definition(
        self,
        tenant_id: str,
        repo_def_id: str,
    ) -> RepositoryDefinition:
        existing = self.get_repo_definition(tenant_id, repo_def_id)
        if existing is None:
            raise KeyError(f"Repository definition {repo_def_id} not found")
        if existing.archived_at is not None:
            return existing
        updated = existing.model_copy(update={"archived_at": utc_now()})
        return self.replace_repo_definition(tenant_id, updated)

    def restore_repo_definition(
        self,
        tenant_id: str,
        repo_def_id: str,
    ) -> RepositoryDefinition:
        existing = self.get_repo_definition(tenant_id, repo_def_id)
        if existing is None:
            raise KeyError(f"Repository definition {repo_def_id} not found")
        if existing.archived_at is None:
            return existing
        updated = existing.model_copy(update={"archived_at": None})
        return self.replace_repo_definition(tenant_id, updated)

    def update_repo_definition_teams(
        self,
        tenant_id: str,
        repo_def_id: str,
        team_ids: list[str],
    ) -> RepositoryDefinitionUpdateTeamsResponse:
        db = self.load_tenant_db(tenant_id)
        if repo_def_id not in db.repo_definitions:
            raise KeyError(f"Repository definition {repo_def_id} not found")
        existing = db.repo_definitions[repo_def_id]
        updated = existing.model_copy(update={"team_ids": team_ids})
        self.replace_repo_definition(tenant_id, updated)
        return RepositoryDefinitionUpdateTeamsResponse(
            tenant_id=tenant_id,
            repo_def_id=repo_def_id,
            team_ids=team_ids,
        )

    # ------------------------------------------------------------------
    # Checkouts
    # ------------------------------------------------------------------

    def create_checkout(self, checkout: Checkout) -> Checkout:
        db = self.load_tenant_db(checkout.tenant_id)
        if checkout.checkout_id in db.checkouts:
            raise ValueError(f"Checkout {checkout.checkout_id} already exists")
        db.checkouts[checkout.checkout_id] = checkout
        self.save_tenant_db(checkout.tenant_id, db)
        return checkout

    def get_checkout(self, tenant_id: str, checkout_id: str) -> Checkout | None:
        db = self.load_tenant_db(tenant_id)
        return db.checkouts.get(checkout_id)

    def list_checkouts(self, tenant_id: str) -> list[Checkout]:
        db = self.load_tenant_db(tenant_id)
        return list(db.checkouts.values())

    def list_checkouts_for_repo(self, tenant_id: str, repo_def_id: str) -> list[Checkout]:
        db = self.load_tenant_db(tenant_id)
        return [c for c in db.checkouts.values() if c.repo_def_id == repo_def_id]
