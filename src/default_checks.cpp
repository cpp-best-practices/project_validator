#include <project_validator/checks/coverage_check.hpp>
#include <project_validator/checks/ctest_check.hpp>
#include <project_validator/checks/has_ci_check.hpp>
#include <project_validator/checks/platform_matrix_check.hpp>
#include <project_validator/default_checks.hpp>

namespace project_validator {

Registry default_registry()
{
  Registry registry;
  registry.emplace<Has_CI_Check>();
  registry.emplace<CTest_Check>();
  registry.emplace<Coverage_Check>();
  registry.emplace<Platform_Matrix_Check>();
  return registry;
}

}// namespace project_validator
