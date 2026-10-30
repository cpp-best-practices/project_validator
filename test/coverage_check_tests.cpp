#include "temp_project.hpp"

#include <project_validator/checks/coverage_check.hpp>

#include <catch2/catch_test_macros.hpp>
#include <catch2/matchers/catch_matchers_string.hpp>

#include <array>
#include <string_view>

using Catch::Matchers::ContainsSubstring;
using project_validator::Status;

TEST_CASE("Coverage_Check detects branch coverage reporting in CI scripts")
{
  constexpr auto workflows = std::to_array<std::string_view>({
    "run: gcovr -r . --txt-metric branch",
    "run: gcovr --fail-under-branch 80",
    "run: lcov --capture --rc branch_coverage=1 -o cov.info",
    "run: lcov --rc lcov_branch_coverage=1",
    "run: llvm-cov report --show-branch-summary",
    "run: llvm-cov show -show-branches=count",
  });

  for (const auto workflow : workflows) {
    INFO(workflow);
    project_validator::test::Temp_Project temp;
    temp.write(".github/workflows/coverage.yml", workflow);

    CHECK(project_validator::Coverage_Check{}.run(temp.project()).status == Status::pass);
  }
}

TEST_CASE("Coverage_Check detects branch coverage configured in CMake")
{
  project_validator::test::Temp_Project temp;
  temp.write("cmake/Coverage.cmake", "set(GCOVR_ARGS --txt-metric=branch)\n");

  CHECK(project_validator::Coverage_Check{}.run(temp.project()).status == Status::pass);
}

TEST_CASE("Coverage_Check fails when only line coverage is collected")
{
  project_validator::test::Temp_Project temp;
  temp.write(".github/workflows/coverage.yml", "run: gcovr -r . --xml coverage.xml\n")
    .write("CMakeLists.txt", "add_compile_options(--coverage)\n");

  const auto result = project_validator::Coverage_Check{}.run(temp.project());
  CHECK(result.status == Status::fail);
  CHECK_THAT(result.message, ContainsSubstring("branch coverage"));
}

TEST_CASE("Coverage_Check reports path coverage when present")
{
  project_validator::test::Temp_Project temp;
  temp.write(".github/workflows/coverage.yml", "run: gcovr --txt-metric branch\n")
    .write("CMakeLists.txt", "add_compile_options(-fpath-coverage)\n");

  const auto result = project_validator::Coverage_Check{}.run(temp.project());
  CHECK(result.status == Status::pass);
  CHECK_THAT(result.message, ContainsSubstring("path coverage is checked"));
}

TEST_CASE("Coverage_Check suggests path coverage when absent")
{
  project_validator::test::Temp_Project temp;
  temp.write(".github/workflows/coverage.yml", "run: gcovr --txt-metric branch\n");

  const auto result = project_validator::Coverage_Check{}.run(temp.project());
  CHECK(result.status == Status::pass);
  CHECK_THAT(result.message, ContainsSubstring("consider adding path coverage"));
}
