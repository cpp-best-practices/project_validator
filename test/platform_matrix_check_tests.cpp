#include "temp_project.hpp"

#include <project_validator/checks/platform_matrix_check.hpp>

#include <catch2/catch_test_macros.hpp>
#include <catch2/matchers/catch_matchers_string.hpp>

using Catch::Matchers::ContainsSubstring;
using project_validator::Status;

namespace {
constexpr auto full_matrix = R"(
jobs:
  build:
    strategy:
      matrix:
        os: [ubuntu-latest, windows-latest, macos-latest]
        compiler: [gcc, clang, msvc]
)";
}

TEST_CASE("Platform_Matrix_Check passes for a multi OS and multi compiler matrix")
{
  project_validator::test::Temp_Project temp;
  temp.write(".github/workflows/ci.yml", full_matrix);

  const auto result = project_validator::Platform_Matrix_Check{}.run(temp.project());
  CHECK(result.status == Status::pass);
  CHECK_THAT(result.message, ContainsSubstring("linux"));
  CHECK_THAT(result.message, ContainsSubstring("windows"));
  CHECK_THAT(result.message, ContainsSubstring("macos"));
  CHECK_THAT(result.message, ContainsSubstring("gcc"));
  CHECK_THAT(result.message, ContainsSubstring("clang"));
  CHECK_THAT(result.message, ContainsSubstring("msvc"));
}

TEST_CASE("Platform_Matrix_Check combines all CI files")
{
  project_validator::test::Temp_Project temp;
  temp.write(".github/workflows/linux.yml", "runs-on: ubuntu-22.04\nenv:\n  CXX: g++-13\n")
    .write("appveyor.yml", "image: Visual Studio 2022\n");

  CHECK(project_validator::Platform_Matrix_Check{}.run(temp.project()).status == Status::pass);
}

TEST_CASE("Platform_Matrix_Check fails for a single operating system")
{
  project_validator::test::Temp_Project temp;
  temp.write(".github/workflows/ci.yml", "runs-on: ubuntu-latest\nmatrix:\n  compiler: [gcc, clang]\n");

  const auto result = project_validator::Platform_Matrix_Check{}.run(temp.project());
  CHECK(result.status == Status::fail);
  CHECK_THAT(result.message, ContainsSubstring("operating systems"));
}

TEST_CASE("Platform_Matrix_Check fails for a single compiler")
{
  project_validator::test::Temp_Project temp;
  temp.write(".github/workflows/ci.yml", "os: [ubuntu-latest, macos-latest]\nrun: clang-tidy src && clang-format --dry-run\nCXX: g++\n");

  const auto result = project_validator::Platform_Matrix_Check{}.run(temp.project());
  CHECK(result.status == Status::fail);
  CHECK_THAT(result.message, ContainsSubstring("compilers"));
}

TEST_CASE("Platform_Matrix_Check thresholds are configurable")
{
  project_validator::test::Temp_Project temp;
  temp.write(".github/workflows/ci.yml", "runs-on: ubuntu-latest\nCXX: g++\n");

  const auto relaxed = project_validator::Platform_Matrix_Check{ project_validator::Platform_Matrix_Check::Thresholds{
    .minimum_operating_systems = 1, .minimum_compilers = 1 } };
  CHECK(relaxed.run(temp.project()).status == Status::pass);
}

TEST_CASE("Platform_Matrix_Check fails without CI files")
{
  const project_validator::test::Temp_Project temp;

  CHECK(project_validator::Platform_Matrix_Check{}.run(temp.project()).status == Status::fail);
}
