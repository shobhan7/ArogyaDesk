import logging
import threading
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app import __version__
from app.cache import build_cache
from app.config import Settings
from app.errors import AppError
from app.models import Base
from app.routers import auth, catalog, visits
from app.seed import seed_demo
from app.throttle import LoginThrottle

logger = logging.getLogger("arogyadesk")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    settings.validate_runtime()
    engine = _engine(settings.database_url)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    app = FastAPI(
        title="ArogyaDesk API",
        version=__version__,
        description=(
            "Outpatient appointment, queue, prescription, and billing API "
            "for multi-clinic OPD operations."
        ),
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.cache = build_cache(settings)
    app.state.throttle = LoginThrottle()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(auth.router)
    app.include_router(catalog.router)
    app.include_router(visits.router)

    @app.get("/health", tags=["Health"])
    def health():
        return {"status": "ok", "service": "arogyadesk"}

    @app.get("/", tags=["Health"])
    def root():
        return {"name": "ArogyaDesk", "version": __version__, "docs": "/docs"}

    @app.exception_handler(AppError)
    async def on_app_error(_request: Request, exc: AppError):
        phrase = HTTPStatus(exc.status_code).phrase
        return JSONResponse(
            status_code=exc.status_code,
            content={"status": exc.status_code, "error": phrase, "message": exc.message},
        )

    @app.exception_handler(RequestValidationError)
    async def on_validation(_request: Request, exc: RequestValidationError):
        details = []
        for err in exc.errors():
            loc = ".".join(str(part) for part in err["loc"])
            details.append({"field": loc, "issue": err["msg"]})
        return JSONResponse(
            status_code=422,
            content={
                "status": 422,
                "error": "Unprocessable Entity",
                "message": "Request validation failed",
                "details": details,
            },
        )

    if settings.seed:
        db = session_factory()
        try:
            seed_demo(db, settings)
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    if settings.kafka_enabled:
        _start_kafka(app)
    return app


def _engine(url: str):
    if url.startswith("sqlite"):
        engine = create_engine(
            url,
            connect_args={"check_same_thread": False, "timeout": 30},
            pool_pre_ping=True,
            poolclass=NullPool,
        )

        @event.listens_for(engine, "connect")
        def _sqlite(dbapi_conn, _record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

        return engine
    return create_engine(url, pool_pre_ping=True)


def _start_kafka(app: FastAPI) -> None:
    settings = app.state.settings
    try:
        from app.outbox import KafkaPublisher, consume_notification, relay_pending
    except Exception:
        logger.exception("Kafka helpers could not be imported")
        return

    try:
        publisher = KafkaPublisher(settings.kafka_bootstrap, settings.kafka_topic)
    except Exception:
        logger.exception("Kafka producer is not reachable. The API will keep writing the outbox.")
        publisher = None

    if publisher is not None:

        def relay_loop():
            while True:
                db = app.state.session_factory()
                try:
                    relay_pending(db, publisher)
                    db.commit()
                except Exception:
                    db.rollback()
                    logger.exception("Outbox relay failed")
                finally:
                    db.close()
                threading.Event().wait(2)

        threading.Thread(target=relay_loop, name="outbox-relay", daemon=True).start()

    def consume_loop():
        try:
            from kafka import KafkaConsumer

            consumer = KafkaConsumer(
                settings.kafka_topic,
                bootstrap_servers=settings.kafka_bootstrap.split(","),
                group_id="arogyadesk-notifications",
                auto_offset_reset="earliest",
                enable_auto_commit=True,
            )
        except Exception:
            logger.exception("Kafka consumer is not reachable")
            return
        for message in consumer:
            db = app.state.session_factory()
            try:
                consume_notification(db, message.value.decode())
                db.commit()
            except Exception:
                db.rollback()
                logger.exception("Notification consume failed")
            finally:
                db.close()

    threading.Thread(target=consume_loop, name="notification-consumer", daemon=True).start()
