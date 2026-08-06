from pydantic import BaseModel


class DimensionsResult(BaseModel):
    weight_kg: float = 0.0
    length_cm: float = 0.0
    width_cm: float = 0.0
    height_cm: float = 0.0
