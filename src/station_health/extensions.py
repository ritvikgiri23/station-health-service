"""Flask extension singletons, bound to an app in `create_app`."""

from flask_migrate import Migrate
from flask_smorest import Api
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# Objects stay usable after commit without a reload query (ingest returns what it stored).
db = SQLAlchemy(model_class=Base, session_options={"expire_on_commit": False})
migrate = Migrate()
api = Api()
