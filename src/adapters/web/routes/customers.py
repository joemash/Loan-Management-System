import uuid

from fastapi import APIRouter, Depends

from src.adapters.web.dependencies import Inject
from src.adapters.web.schemas import CustomerResponse
from src.adapters.web.security import require_authenticated
from src.application.ports.usecases import ICustomerUseCases

router = APIRouter(prefix="/customers", tags=["customers"], dependencies=[Depends(require_authenticated)])


@router.get("/{customer_id}", response_model=CustomerResponse, summary="Customer profile and credit line")
def get_customer(customer_id: uuid.UUID, customers: ICustomerUseCases = Inject(ICustomerUseCases)):
    return customers.get(customer_id)
