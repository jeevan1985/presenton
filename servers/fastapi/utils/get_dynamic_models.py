from typing import List, Optional
from pydantic import Field
from models.presentation_outline_model import (
    PresentationOutlineModel,
    SlideOutlineModel,
)
from models.presentation_structure_model import PresentationStructureModel


class SlideOutlineModelWithValidation(SlideOutlineModel):
    title: str = Field(
        description="Title of the slide in about 3 to 5 words",
        min_length=10,
        max_length=50,
    )


def get_presentation_outline_model_with_n_slides(n_slides: int):
    class PresentationOutlineModelWithNSlides(PresentationOutlineModel):
        title: str = Field(
            description="Title of the presentation in about 3 to 8 words",
            min_length=10,
            max_length=50,
        )
        slides: List[SlideOutlineModelWithValidation] = Field(
            description="List of slides", min_items=n_slides, max_items=n_slides
        )

    return PresentationOutlineModelWithNSlides


def get_presentation_structure_model_with_n_slides(n_slides: int):
    class PresentationStructureModelWithNSlides(PresentationStructureModel):
        slides: List[int] = Field(
            description="List of slide layouts",
            min_items=n_slides,
            max_items=n_slides,
        )

    return PresentationStructureModelWithNSlides
