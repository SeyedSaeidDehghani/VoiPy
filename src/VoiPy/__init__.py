__all__ = ['__version__', 'Call', 'debug']

from .helper import debug
from .voip import *

version_info = (1, 0, 8)

__version__ = ".".join([str(x) for x in version_info])

__author__ = "Seyed_Saeid_Dehghani"
