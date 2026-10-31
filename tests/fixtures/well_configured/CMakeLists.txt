cmake_minimum_required(VERSION 3.21)
project(well_configured LANGUAGES CXX)

set(CMAKE_CXX_EXTENSIONS OFF)

if(MSVC)
  add_compile_options(/W4 /permissive-)
else()
  add_compile_options(-Wall -Wextra -Wpedantic -Wshadow -Wconversion)
endif()

option(ENABLE_COVERAGE "Instrument for coverage" OFF)
if(ENABLE_COVERAGE)
  add_compile_options(--coverage -fcondition-coverage)
  add_link_options(--coverage)
endif()

include(CTest)
add_subdirectory(test)
