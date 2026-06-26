from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Response, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from app.dependencies import get_async_db, get_current_organization
from app.services.step_service import StepService
from app.services import parquet_store
from app.models.user import User
from app.models.organization import Organization
from app.core.auth import current_user
from app.core.permissions_decorator import requires_permission
from app.ee.audit.service import audit_service
import io
import logging
from app.schemas.step_schema import StepSchema


class StepQueryRequest(BaseModel):
    select: List[str] = Field(default_factory=list)
    filters: List[dict] = Field(default_factory=list)
    group_by: List[str] = Field(default_factory=list)
    aggs: List[dict] = Field(default_factory=list)
    order_by: List[dict] = Field(default_factory=list)
    limit: int = 100
    offset: int = 0

router = APIRouter(tags=["steps"])
step_service = StepService()

@router.get("/steps/{step_id}/export", response_class=Response)
@requires_permission('view_reports')
async def export_step(
    step_id: str,
    request: Request,
    current_user: User = Depends(current_user),
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_async_db)
):
    logging.info(f"CSV export request received for step {step_id}")
    try:
        df, step = await step_service.export_step_to_csv(db, step_id)

        csv_buffer = io.StringIO()
        df.to_csv(csv_buffer, index=False)
        csv_buffer.seek(0)

        try:
            await audit_service.log(
                db=db,
                organization_id=organization.id,
                action="data.exported",
                user_id=current_user.id,
                resource_type="step",
                resource_id=step_id,
                details={"format": "csv", "row_count": len(df)},
                request=request,
            )
        except Exception:
            pass

        response = Response(content=csv_buffer.getvalue(), media_type="text/csv")
        widget_title = "".join(c for c in step.widget.title if c.isalnum() or c in (' ', '_')).rstrip()
        file_name = f"{widget_title}-{step.slug}.csv".replace(" ", "_")
        response.headers["Content-Disposition"] = f"attachment; filename=\"{file_name}\""
        return response

    except ValueError as e:
        logging.warning(f"Value error in export_step route for step {step_id}: {str(e)}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logging.error(f"Error in export_step route for step {step_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error during export: {str(e)}") 


@router.get("/steps/{step_id}", response_model=StepSchema)
@requires_permission('view_reports')
async def get_step(
    step_id: str,
    current_user: User = Depends(current_user),
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_async_db)
):
    step = await step_service.get_step_by_id(db, step_id)
    if not step:
        raise HTTPException(status_code=404, detail="Step not found")
    return StepSchema.from_orm(step)


@router.post("/steps/{step_id}/query")
@requires_permission('view_reports')
async def query_step(
    step_id: str,
    body: StepQueryRequest,
    current_user: User = Depends(current_user),
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_async_db)
):
    step = await step_service.get_step_by_id(db, step_id)
    if not step:
        raise HTTPException(status_code=404, detail="Step not found")
    try:
        return parquet_store.query(step.data, body.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))