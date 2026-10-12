import os

from . import models
from .models import User, format_name as fmt


def create_user(raw: str) -> User:
    user = User(fmt(raw))
    user.describe()
    return user


def default_user() -> models.User:
    return create_user(os.environ.get("USER", "anon"))


class Admin(models.User):
    def label(self) -> str:
        return super().label().upper()
