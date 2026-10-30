#include "temp_project.hpp"

#include <project_validator/default_checks.hpp>

#include <catch2/catch_test_macros.hpp>

#include <algorithm>
#include <string>
#include <vector>

TEST_CASE("Default registry contains the initial set of checks")
{
  const auto registry = project_validator::default_registry();

  const project_validator::test::Temp_Project temp;
  const auto reports = registry.run_all(temp.project());

  std::vector<std::string> names;
  std::ranges::transform(reports, std::back_inserter(names), &project_validator::Check_Report::name);

  CHECK(names == std::vector<std::string>{ "has-ci", "ctest", "coverage", "platform-matrix" });
  CHECK_FALSE(project_validator::all_passed(reports));
}
