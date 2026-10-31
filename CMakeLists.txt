cmake_minimum_required(VERSION 3.21)

# The validator itself is pure Python; CMake only drives its tests through CTest,
# so the repository can be validated by its own tool like any other CMake project.
project(
  project_validator
  VERSION 0.1.0
  DESCRIPTION "Validate CMake based projects against C++ Best Practices"
  LANGUAGES NONE)

find_package(Python3 3.14 REQUIRED COMPONENTS Interpreter)

enable_testing()

add_test(
  NAME unit_tests
  COMMAND Python3::Interpreter -W error -m unittest
  WORKING_DIRECTORY ${PROJECT_SOURCE_DIR})

add_test(
  NAME self_validation
  COMMAND Python3::Interpreter -m project_validator --strict ${PROJECT_SOURCE_DIR}
  WORKING_DIRECTORY ${PROJECT_SOURCE_DIR})
