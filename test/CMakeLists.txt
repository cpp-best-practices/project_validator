include(FetchContent)

FetchContent_Declare(
  Catch2
  GIT_REPOSITORY https://github.com/catchorg/Catch2.git
  GIT_TAG v3.7.1
  GIT_SHALLOW TRUE)
FetchContent_MakeAvailable(Catch2)

list(APPEND CMAKE_MODULE_PATH ${catch2_SOURCE_DIR}/extras)
include(Catch)

add_executable(
  project_validator_tests
  temp_project.cpp
  project_tests.cpp
  registry_tests.cpp
  has_ci_check_tests.cpp
  ctest_check_tests.cpp
  coverage_check_tests.cpp
  platform_matrix_check_tests.cpp
  default_checks_tests.cpp)
target_link_libraries(project_validator_tests PRIVATE project_validator_lib project_validator_options Catch2::Catch2WithMain)

catch_discover_tests(project_validator_tests)

add_test(NAME self_validation COMMAND project_validator ${PROJECT_SOURCE_DIR})
