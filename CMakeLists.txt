cmake_minimum_required(VERSION 3.21)

project(
  project_validator
  VERSION 0.1.0
  DESCRIPTION "Validate CMake based projects against C++ Best Practices"
  LANGUAGES CXX)

option(PROJECT_VALIDATOR_BUILD_TESTS "Build the project_validator tests" ${PROJECT_IS_TOP_LEVEL})
option(PROJECT_VALIDATOR_WARNINGS_AS_ERRORS "Treat compiler warnings as errors" OFF)
option(PROJECT_VALIDATOR_ENABLE_COVERAGE "Instrument the build for coverage reporting" OFF)

add_library(project_validator_options INTERFACE)
target_compile_features(project_validator_options INTERFACE cxx_std_20)

if(MSVC)
  target_compile_options(project_validator_options INTERFACE /W4 /permissive- $<$<BOOL:${PROJECT_VALIDATOR_WARNINGS_AS_ERRORS}>:/WX>)
else()
  target_compile_options(
    project_validator_options
    INTERFACE -Wall
              -Wextra
              -Wpedantic
              -Wshadow
              -Wconversion
              -Wsign-conversion
              -Wnon-virtual-dtor
              -Wold-style-cast
              -Wcast-align
              -Woverloaded-virtual
              -Wnull-dereference
              -Wdouble-promotion
              -Wformat=2
              -Wimplicit-fallthrough
              $<$<BOOL:${PROJECT_VALIDATOR_WARNINGS_AS_ERRORS}>:-Werror>)
endif()

if(PROJECT_VALIDATOR_ENABLE_COVERAGE)
  target_compile_options(project_validator_options INTERFACE --coverage -O0 -g)
  target_link_options(project_validator_options INTERFACE --coverage)
endif()

add_subdirectory(src)

if(PROJECT_VALIDATOR_BUILD_TESTS)
  enable_testing()
  add_subdirectory(test)
endif()
