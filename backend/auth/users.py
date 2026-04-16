import uuid
from typing import AsyncGenerator

from fastapi import Depends
from fastapi.security import OAuth2PasswordRequestForm
from fastapi_users import FastAPIUsers, BaseUserManager, UUIDIDMixin, exceptions
from fastapi_users.authentication import AuthenticationBackend, BearerTransport, JWTStrategy
from fastapi_users.db import SQLAlchemyUserDatabase
from fastapi_users.password import PasswordHelper
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import SECRET, API_URL_PREFIX
from backend.db.session import async_get_session
from backend.db.models import User, ApiGroups


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    reset_password_token_secret = SECRET
    verification_token_secret = SECRET

    async def get_by_username(self, username: str) -> User:
        user = await self.user_db.get_by_username(username)
        if user is None:
            raise exceptions.UserNotExists()
        return user

    async def authenticate(self, credentials: OAuth2PasswordRequestForm) -> User | None:
        try:
            if "@" in credentials.username:
                user = await self.get_by_email(credentials.username)
            else:
                user = await self.get_by_username(credentials.username)
        except exceptions.UserNotExists:
            self.password_helper.hash(credentials.password)
            return None

        verified, updated_password_hash = self.password_helper.verify_and_update(
            credentials.password, user.hashed_password
        )
        if not verified:
            return None
        if updated_password_hash is not None:
            await self.user_db.update(user, {"hashed_password": updated_password_hash})

        if not user.is_superuser:
            session = self.user_db.session
            result = await session.execute(
                select(ApiGroups.is_active).where(ApiGroups.group_id == user.group_id)
            )
            group_active = result.scalar_one_or_none()
            if group_active is not True:
                return None

        return user


class SQLAlchemyUserDatabasePatched(SQLAlchemyUserDatabase):
    async def get_by_username(self, username: str):
        statement = select(self.user_table).where(self.user_table.user_name == username)
        return await self._get_user(statement)


async def async_get_user_db(session: AsyncSession = Depends(async_get_session)):
    yield SQLAlchemyUserDatabasePatched(session, User)


async def get_user_manager(user_db=Depends(async_get_user_db)) -> AsyncGenerator[UserManager, None]:
    yield UserManager(user_db)


bearer_transport = BearerTransport(tokenUrl=f"{API_URL_PREFIX}/auth/jwt/login".lstrip("/"))


def get_jwt_strategy() -> JWTStrategy:
    return JWTStrategy(secret=SECRET, lifetime_seconds=60 * 60 * 24 * 7)  # 7 days


auth_backend = AuthenticationBackend(
    name="jwt",
    transport=bearer_transport,
    get_strategy=get_jwt_strategy,
)

fastapi_users = FastAPIUsers[User, uuid.UUID](get_user_manager, [auth_backend])
current_active_user = fastapi_users.current_user(active=True)
current_active_user_or_none = fastapi_users.current_user(active=True, optional=True)
password_helper = PasswordHelper()
