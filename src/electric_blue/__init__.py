"""electric-blue — drop-folder transcription pipeline."""

__version__ = "0.1.0"

from .config import Config
from .models import Segment, TranscriptInfo

__all__ = ["Config", "Segment", "TranscriptInfo", "__version__"]
