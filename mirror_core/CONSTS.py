# coding=utf-8
import os

__VERSION_TUPLE__ = (0, 0, 1, "")
__VERSION__ = ".".join(str(x) for x in __VERSION_TUPLE__).rstrip(".")
__AUTHOR__ = "Leo"
__GITHUB_URL__ = "https://github.com/BigDevil82/EasyMirror"
ZMIRROR_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
