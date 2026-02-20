"""
PFM - Pure Fucking Magic
AI agent output container format.

Speed > Indexing > Human Readability > AI Usefulness
"""

__version__ = "0.1.7"
__format_version__ = "1.0"

from pfm.spec import MAGIC, FORMAT_VERSION, SECTION_TYPES
from pfm.writer import PFMWriter
from pfm.reader import PFMReader
from pfm.document import PFMDocument
from pfm.stream import PFMStreamWriter
