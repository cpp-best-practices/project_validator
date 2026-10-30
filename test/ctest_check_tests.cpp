#include "temp_project.hpp"

#include <project_validator/checks/ctest_check.hpp>

#include <catch2/catch_test_macros.hpp>
#include <catch2/matchers/catch_matchers_string.hpp>

using Catch::Matchers::ContainsSubstring;
using project_validator::Status;

TEST_CASE("CTest_Check passes when testing is enabled and tests are registered")
{
  project_validator::test::Temp_Project temp;
  temp.write("CMakeLists.txt", "project(p)\nenable_testing()\nadd_subdirectory(test)\n")
    .write("test/CMakeLists.txt", "add_test(NAME unit COMMAND unit)\n");

  CHECK(project_validator::CTest_Check{}.run(temp.project()).status == Status::pass);
}

TEST_CASE("CTest_Check accepts include(CTest) and test discovery commands in any case")
{
  project_validator::test::Temp_Project temp;
  temp.write("CMakeLists.txt", "INCLUDE( CTest )\n").write("test/CMakeLists.txt", "Catch_Discover_Tests(tests)\n");

  CHECK(project_validator::CTest_Check{}.run(temp.project()).status == Status::pass);
}

TEST_CASE("CTest_Check fails when testing is never enabled")
{
  project_validator::test::Temp_Project temp;
  temp.write("CMakeLists.txt", "project(p)\nadd_test(NAME unit COMMAND unit)\n");

  const auto result = project_validator::CTest_Check{}.run(temp.project());
  CHECK(result.status == Status::fail);
  CHECK_THAT(result.message, ContainsSubstring("enable_testing"));
}

TEST_CASE("CTest_Check fails when no tests are registered")
{
  project_validator::test::Temp_Project temp;
  temp.write("CMakeLists.txt", "project(p)\nenable_testing()\n");

  const auto result = project_validator::CTest_Check{}.run(temp.project());
  CHECK(result.status == Status::fail);
  CHECK_THAT(result.message, ContainsSubstring("no tests"));
}

TEST_CASE("CTest_Check fails for projects without CMake files")
{
  const project_validator::test::Temp_Project temp;

  const auto result = project_validator::CTest_Check{}.run(temp.project());
  CHECK(result.status == Status::fail);
  CHECK_THAT(result.message, ContainsSubstring("no CMake files"));
}
