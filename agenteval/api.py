"""FastAPI mock business API for resource-allocation agents."""
import os
from contextlib import asynccontextmanager
from datetime import date
from fastapi import Depends, FastAPI, Header, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from agenteval.database import create_schema, make_engine, make_session_factory
from agenteval.models import Allocation
from agenteval.services import BusinessError, cancel_allocation, create_allocation, get_availability, get_employee, get_project

class ErrorBody(BaseModel):
    code: str
    message: str
class ErrorResponse(BaseModel):
    error: ErrorBody
class EmployeeResponse(BaseModel):
    employee_id: str
    name: str
    department: str
    capacity_percentage: int
    status: str
class ProjectResponse(BaseModel):
    project_id: str
    project_name: str
    start_date: date
    end_date: date
    status: str
class AvailabilityResponse(BaseModel):
    employee_id: str
    capacity_percentage: int
    allocated_percentage: int
    available_percentage: int
    start_date: date
    end_date: date
class AllocationCreate(BaseModel):
    employee_id: str
    project_id: str
    allocation_percentage: int = Field(ge=1, le=100)
    start_date: date
    end_date: date
class AllocationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    allocation_id: int
    employee_id: str
    project_id: str
    allocation_percentage: int
    start_date: date
    end_date: date
    status: str

def create_app(database_url: str | None = None) -> FastAPI:
    database_url = database_url or os.getenv("AGENTEEVAL_DATABASE_URL", "sqlite:///./agenteval.db")
    engine = make_engine(database_url)
    sessions = make_session_factory(engine)
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        create_schema(engine)
        yield
        engine.dispose()
    app = FastAPI(title="AgentEval Gym Resource API", version="0.1.0", lifespan=lifespan)
    app.state.engine = engine
    def db_session():
        with sessions() as session:
            yield session
    @app.exception_handler(BusinessError)
    async def business_error_handler(_request: Request, exc: BusinessError):
        return JSONResponse(status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
            headers={"Retry-After": "1"} if exc.status_code == 503 else None)
    @app.get("/health")
    def health():
        return {"status": "ok"}
    @app.get("/employees/{employee_id}", response_model=EmployeeResponse)
    def employee_detail(employee_id: str, session: Session = Depends(db_session)):
        return get_employee(session, employee_id)
    @app.get("/projects/{project_id}", response_model=ProjectResponse)
    def project_detail(project_id: str, session: Session = Depends(db_session)):
        return get_project(session, project_id)
    @app.get("/employees/{employee_id}/availability", response_model=AvailabilityResponse,
        responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}})
    def availability(employee_id: str, start_date: date, end_date: date, session: Session = Depends(db_session)):
        return get_availability(session, employee_id, start_date, end_date)
    @app.get("/allocations", response_model=list[AllocationResponse])
    def allocations(session: Session = Depends(db_session)):
        return list(session.query(Allocation).order_by(Allocation.allocation_id))
    @app.post("/allocations", response_model=AllocationResponse, status_code=201,
        responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}, 503: {"model": ErrorResponse}})
    def assign_resource(body: AllocationCreate, response: Response,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        session: Session = Depends(db_session)):
        allocation, replayed = create_allocation(session, **body.model_dump(), idempotency_key=idempotency_key)
        if replayed:
            response.headers["Idempotency-Replayed"] = "true"
        return allocation
    @app.delete("/allocations/{allocation_id}", status_code=204,
        responses={404: {"model": ErrorResponse}, 503: {"model": ErrorResponse}})
    def remove_allocation(allocation_id: int, session: Session = Depends(db_session)):
        cancel_allocation(session, allocation_id)
        return Response(status_code=204)
    return app

app = create_app()
