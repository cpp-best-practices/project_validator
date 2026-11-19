"""C++: built with CMake or Meson, judged by its compilers. C++ is judged on its own, with C++'s flags
(`CMAKE_CXX_FLAGS`, `cpp_std`), never C's; what the two share is in `project_validator.c_family`, and the shape of
their ecosystems in the C profile."""

from __future__ import annotations

from project_validator.ecosystems.c import CXX_SOURCES, CXX_TEMPLATES, c_family_ecosystem

CXX = c_family_ecosystem("C++", CXX_SOURCES, CXX_TEMPLATES)
