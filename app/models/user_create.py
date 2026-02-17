from pydantic import BaseModel


class UserCreate(BaseModel):
    email: str
    first_name: str
    last_name: str
    address: str | None = None
    city: str | None = None
    state: str | None = None
    zipcode: str | None = None
    phone_number: str | None = None
