"""Print fresh secrets for .env (SECRET_KEY, ENCRYPTION_KEY, POSTGRES_PASSWORD)."""
import secrets

from cryptography.fernet import Fernet

print(f"SECRET_KEY={secrets.token_urlsafe(48)}")
print(f"ENCRYPTION_KEY={Fernet.generate_key().decode()}")
print(f"POSTGRES_PASSWORD={secrets.token_urlsafe(24)}")
