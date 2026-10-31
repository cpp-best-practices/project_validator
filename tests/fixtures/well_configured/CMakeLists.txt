cmake_minimum_required(VERSION 3.21)
project(well_configured LANGUAGES CXX)

option(ENABLE_COVERAGE "Instrument for coverage" OFF)
if(ENABLE_COVERAGE)
  add_compile_options(--coverage -fcondition-coverage)
  add_link_options(--coverage)
endif()

option(WARNINGS_AS_ERRORS "Treat compiler warnings as errors" ON)
if(WARNINGS_AS_ERRORS)
  add_compile_options(-Werror)
endif()

include(CTest)
add_subdirectory(test)
