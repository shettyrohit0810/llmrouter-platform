from typing import Optional

from backend.api.repositories.base import BaseRepository
from backend.db.models.user import APIKey, OAuthAccount, RefreshToken, User


class UserRepository(BaseRepository[User]):
    model = User

    def get_by_email(self, email: str) -> Optional[User]:
        return self.db.query(User).filter(User.email == email).first()


class OAuthAccountRepository(BaseRepository[OAuthAccount]):
    model = OAuthAccount

    def get_by_provider_account(
        self, provider: str, provider_account_id: str
    ) -> Optional[OAuthAccount]:
        return (
            self.db.query(OAuthAccount)
            .filter(
                OAuthAccount.provider == provider,
                OAuthAccount.provider_account_id == provider_account_id,
            )
            .first()
        )


class RefreshTokenRepository(BaseRepository[RefreshToken]):
    model = RefreshToken

    def get_by_hash(self, token_hash: str) -> Optional[RefreshToken]:
        return self.db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()


class APIKeyRepository(BaseRepository[APIKey]):
    model = APIKey

    def get_by_hash(self, key_hash: str) -> Optional[APIKey]:
        return self.db.query(APIKey).filter(APIKey.key_hash == key_hash).first()

    def list_for_user(self, user_id) -> list[APIKey]:
        return list(self.db.query(APIKey).filter(APIKey.created_by == user_id).all())
