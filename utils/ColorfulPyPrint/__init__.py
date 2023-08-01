# -*- coding: UTF-8 -*-
"""
Enjoy printing
Modified by Leo at 2023/07/29 (https://github.com/BigDevil82)

License: GPLv3
original Author: aploium@aploium.com
github: https://github.com/Aploium/ColorfulPyPrint
"""

from __future__ import print_function
from time import time, localtime, strftime

from ._Beep import beep
from .thirdparty import Fore


__author__ = "Leo"
__version__ = "0.0.1"


## 5 print types, used to identify print color
PRINT_TYPE_INFO = 0
PRINT_TYPE_DEBUG = 1
PRINT_TYPE_WARN = 2
PRINT_TYPE_ERROR = 3
PRINT_TYPE_IMPORTANT_NOTICE = 4

# used to format time string in log
TIME_FORMAT_NONE = 0
TIME_FORMAT_TIME = 1
TIME_FORMAT_FULL = 2


class ColorfulPrinter:
    def __init__(self, verbose_level=1, time_level=TIME_FORMAT_FULL) -> None:
        """
        the higher the verbose_level, the more information will be printed
        that is, the info whose verbose level <= verbose_level will be printed
        """
        self.PRINT_VERBOSE_LEVEL = verbose_level
        self.TIME_LEVEL = time_level
        # Define a dictionary mapping print types to section colors and types
        self.print_type_map = {
            PRINT_TYPE_INFO: (Fore.GREEN, "[INFO] "),
            PRINT_TYPE_DEBUG: (Fore.LIGHTBLUE_EX, "[DEBUG] "),
            PRINT_TYPE_WARN: (Fore.YELLOW, "[WARNING] "),
            PRINT_TYPE_ERROR: (Fore.RED, "[ERROR] "),
            PRINT_TYPE_IMPORTANT_NOTICE: (Fore.LIGHTMAGENTA_EX, "[IMPORTANT] "),
        }
        # Define a dictionary mapping time levels to time part
        self.time_level_map = {
            TIME_FORMAT_NONE: "",
            TIME_FORMAT_TIME: "[" + self.__logtime(is_print_date=False) + "] ",
            TIME_FORMAT_FULL: "[" + self.__logtime(is_print_date=True) + "] ",
        }

    def set_print_lower_bound(self, verbose_level=1):
        self.PRINT_VERBOSE_LEVEL = verbose_level

    def get_print_lower_bound(self):
        print("ColorfulPrinter current print lower bound is:", self.PRINT_VERBOSE_LEVEL)
        return self.PRINT_VERBOSE_LEVEL

    def __logtime(self, is_print_date=False, timesep=":", datesep="-"):
        _localtime = localtime(time())
        _dateformat = "%Y" + datesep + "%m" + datesep + "%d"
        _timeformat = "%H" + timesep + "%M" + timesep + "%S"
        if is_print_date:
            return strftime(_dateformat + " " + _timeformat, _localtime)
        else:
            return strftime(_timeformat, _localtime)

    def __printer(
        self,
        content,
        other_info,
        verbose_level,
        print_type=PRINT_TYPE_INFO,
        timelevel=TIME_FORMAT_TIME,
        is_beep=False,
    ):
        # check if print_type is higher than PRINT_LEVEL_LOWER_BOUND
        if verbose_level > self.PRINT_VERBOSE_LEVEL:
            return

        # assembly timelevel string
        time_part = self.time_level_map.get(timelevel, "")

        # Look up the section color and type based on the print type
        color, section_type = self.print_type_map.get(print_type, "")

        # Finally Print
        print_str = color + time_part + section_type
        print_str += str(content)
        if other_info:
            for item in other_info:
                print_str += " " + str(item)
        print_str += Fore.RESET

        # Print to console
        try:
            print(print_str)
        except Exception as e:
            print(Fore.RED + "PRINT ERROR: ", e, Fore.RESET)

        if is_beep:
            try:
                beep()
            except:
                pass

    def important_print(self, output="", *other_inputs, **kwargs):
        para = {
            "v": 0,  # verbose
            "timelevel": self.TIME_LEVEL,
            "is_beep": False,
            "i": 3,  # important level (effect extra prints)
        }
        para.update(kwargs)
        self.__printer(
            output,
            other_inputs,
            para["v"],
            print_type=PRINT_TYPE_IMPORTANT_NOTICE,
            timelevel=para["timelevel"],
            is_beep=para["is_beep"],
        )

    def error(self, output="", *other_inputs, **kwargs):
        para = {
            "v": 0,  # verbose
            "timelevel": self.TIME_LEVEL,
            "is_beep": False,
            "i": 2,  # important level (effect extra prints)
        }
        para.update(kwargs)
        self.__printer(
            output,
            other_inputs,
            para["v"],
            print_type=PRINT_TYPE_ERROR,
            timelevel=para["timelevel"],
            is_beep=para["is_beep"],
        )

    def warn(self, output="", *other_inputs, **kwargs):
        para = {
            "v": 1,  # verbose
            "timelevel": self.TIME_LEVEL,
            "is_beep": False,
            "i": 1,  # important level (effect extra prints)
        }
        para.update(kwargs)
        self.__printer(
            output,
            other_inputs,
            para["v"],
            print_type=PRINT_TYPE_WARN,
            timelevel=para["timelevel"],
            is_beep=para["is_beep"],
        )

    def info(self, output="", *other_inputs, **kwargs):
        para = {
            "v": 2,  # verbose
            "timelevel": self.TIME_LEVEL,
            "is_beep": False,
            "i": 1,  # important level (effect extra prints)
        }
        para.update(kwargs)
        self.__printer(
            output,
            other_inputs,
            para["v"],
            print_type=PRINT_TYPE_INFO,
            timelevel=para["timelevel"],
            is_beep=para["is_beep"],
        )

    def debug(self, output="", *other_inputs, **kwargs):
        para = {
            "v": 3,  # verbose
            "timelevel": self.TIME_LEVEL,
            "is_beep": False,
            "i": 0,  # important level (effect extra prints)
        }
        para.update(kwargs)
        self.__printer(
            output,
            other_inputs,
            para["v"],
            print_type=PRINT_TYPE_DEBUG,
            timelevel=para["timelevel"],
            is_beep=para["is_beep"],
        )
