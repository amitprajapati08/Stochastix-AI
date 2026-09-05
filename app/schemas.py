from pydantic import BaseModel


class TransactionRequestSchema(BaseModel):
    transaction_id: str
    merchant_id: str
    amount: float
    card_token: str
    card_bin: str
    ip_address: str
    device_fingerprint: str
    payment_method: str = "card"
