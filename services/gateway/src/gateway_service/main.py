from gateway_service.app import create_app
from gateway_service.config import GatewaySettings
from gateway_service.infrastructure.database import (
    create_engine,
    create_session_factory,
)
from gateway_service.infrastructure.password_service import PwdlibPasswordService
from gateway_service.infrastructure.token_service import PyJwtTokenService
from gateway_service.infrastructure.unit_of_work import SqlAlchemyUnitOfWork

settings = GatewaySettings()
engine = create_engine(settings.database_url)
session_factory = create_session_factory(engine)
password_service = PwdlibPasswordService()
token_service = PyJwtTokenService(settings)


app = create_app(
    settings=settings,
    engine=engine,
    uow_factory=lambda: SqlAlchemyUnitOfWork(session_factory),
    password_service=password_service,
    token_service=token_service,
)
