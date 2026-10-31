cmake_minimum_required(VERSION 3.21)
project(well_configured LANGUAGES CXX)

set(CMAKE_CXX_EXTENSIONS OFF)

if(MSVC)
  add_compile_options(/W4 /permissive- /sdl /guard:cf)
  add_link_options(/DYNAMICBASE /CETCOMPAT)
else()
  add_compile_options(-Wall -Wextra -Wpedantic -Wshadow -Wconversion)
  add_compile_options(-fstack-protector-strong -fcf-protection -fstack-clash-protection)
  add_compile_definitions(_FORTIFY_SOURCE=3 _GLIBCXX_ASSERTIONS)
endif()

option(ENABLE_COVERAGE "Instrument for coverage" OFF)
if(ENABLE_COVERAGE)
  add_compile_options(--coverage -fcondition-coverage)
  add_link_options(--coverage)
endif()

include(CTest)
add_subdirectory(test)
