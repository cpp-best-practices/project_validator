add_library(
  project_validator_lib
  project.cpp
  registry.cpp
  text_search.cpp
  ci_provider.cpp
  default_checks.cpp
  checks/has_ci_check.cpp
  checks/ctest_check.cpp
  checks/coverage_check.cpp
  checks/platform_matrix_check.cpp)
target_include_directories(project_validator_lib PUBLIC ${PROJECT_SOURCE_DIR}/include)
target_link_libraries(project_validator_lib PRIVATE project_validator_options)
target_compile_features(project_validator_lib PUBLIC cxx_std_20)

add_executable(project_validator main.cpp)
target_link_libraries(project_validator PRIVATE project_validator_lib project_validator_options)
